"""실행 시작 · 중지 · 동시 실행 잠금 · 결과 판정 · 저장 · 보고서"""
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import LiveMetrics, RunConfig, RunSummary, SuiteResult
from ticket_guard_qa.domain.pass_criteria import evaluate_pass_criteria
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileStore
from ticket_guard_qa.reports.html_report import write_html_report
from ticket_guard_qa.reports.json_report import write_json_report
from ticket_guard_qa.settings import Settings
from ticket_guard_qa.system_targets.target_factory import build_system_target
from ticket_guard_qa.system_targets.target_interfaces import SystemTarget
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_repository import RunRepository
from ticket_guard_qa.test_suites.suite_interface import QaSuite, SuiteContext
from ticket_guard_qa.test_suites.suite_registry import get_suite


PROGRESS_TICK_SEC = 1.0


class RunAlreadyActiveError(Exception):
    pass


def create_run_id(started_at: datetime) -> str:
    return f"run-{started_at:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def decide_run_status(summary: RunSummary, is_cancelled: bool) -> RunStatus:
    if is_cancelled:
        return RunStatus.CANCELLED
    suite_outcomes = {result.outcome for result in summary.suite_results}
    if SuiteOutcome.ERROR in suite_outcomes:
        return RunStatus.ERROR
    has_failed_criterion = any(result.is_passed is False for result in summary.criterion_results)
    if SuiteOutcome.FAILED in suite_outcomes or has_failed_criterion:
        return RunStatus.FAILED
    return RunStatus.PASSED


def run_one_suite(suite: QaSuite, context: SuiteContext) -> SuiteResult:
    try:
        return suite.run(context)
    except NotImplementedError as error:
        return SuiteResult(suite.suite_name, SuiteOutcome.SKIPPED, message=str(error))  # 실패 아님
    except Exception as error:  # noqa: BLE001 · 한 묶음 오류가 실행 전체를 멈추지 않게
        return SuiteResult(suite.suite_name, SuiteOutcome.ERROR, message=f"{type(error).__name__}: {error}")


class RunService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        progress_stream: RunProgressStream,
        system_target_builder: Callable[[Settings, TargetKind], SystemTarget] = build_system_target,
    ) -> None:
        self.settings = settings
        self.run_repository = RunRepository(session_factory)
        self.answer_key_repository = AnswerKeyRepository(session_factory)
        self.bot_profile_store = BotProfileStore(session_factory)
        self.progress_stream = progress_stream
        self.system_target_builder = system_target_builder
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._active_run_ends_at: datetime | None = None
        self._cancel_requested_run_ids: set[str] = set()

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    @property
    def active_run_remaining_sec(self) -> float | None:
        if self._active_run_ends_at is None:
            return None
        return max((self._active_run_ends_at - datetime.now(timezone.utc)).total_seconds(), 0.0)

    def measurement_window_sec(self, run_config: RunConfig) -> float:
        if run_config.target_kind is TargetKind.FAKE:
            return float(self.settings.fake_run_duration_sec)  # 가짜 실행 흉내 시간 · .env로 조정
        # TODO(트래픽 생성기 구현 후): run_config.duration_sec 동안 트래픽 유지
        return 0.0

    def run_now(self, run_config: RunConfig) -> RunSummary:
        run_id, run_config, started_at = self._reserve_run(run_config)
        return self._execute(run_id, run_config, started_at)

    def start_in_background(self, run_config: RunConfig) -> str:
        run_id, run_config, started_at = self._reserve_run(run_config)
        threading.Thread(target=self._execute, args=(run_id, run_config, started_at), daemon=True).start()
        return run_id

    def cancel(self, run_id: str) -> None:
        self._cancel_requested_run_ids.add(run_id)  # 묶음 사이에서 멈춤

    def _reserve_run(self, run_config: RunConfig) -> tuple[str, RunConfig, datetime]:
        # 지금 봇 버전을 기록 · 같은 버전끼리만 04 비교 · B3 · B4가 당시 설정을 다시 읽음
        current_versions = self.bot_profile_store.load_current_registry().version_number_by_actor_type()
        run_config = replace(run_config, bot_version_numbers=current_versions)
        with self._lock:  # 동시 실행 금지 · 02 화면 시작 잠금
            if self._active_run_id is not None:
                raise RunAlreadyActiveError(f"이미 실행 중: {self._active_run_id}")
            started_at = datetime.now(timezone.utc)
            run_id = create_run_id(started_at)
            self._active_run_id = run_id
            self._active_run_ends_at = started_at + timedelta(seconds=self.measurement_window_sec(run_config))
        self.run_repository.create_run(run_id, run_config, started_at)
        return run_id, run_config, started_at

    def _execute(self, run_id: str, run_config: RunConfig, started_at: datetime) -> RunSummary:
        summary = RunSummary(run_id, run_config, RunStatus.RUNNING, started_at)
        try:
            context = SuiteContext(
                run_id=run_id,
                run_config=run_config,
                system_target=self.system_target_builder(self.settings, run_config.target_kind),
                answer_key_repository=self.answer_key_repository,
                case_data_dir=self.settings.case_data_dir,
                report_progress=lambda text, **fields: self.progress_stream.publish(run_id, text, **fields),
                bot_profile_registry=self.bot_profile_store.load_registry_for_versions(run_config.bot_version_numbers),
            )
            self._watch_measurement_window(run_id, context.system_target, self.measurement_window_sec(run_config))
            for suite_name in run_config.suite_names:
                if run_id in self._cancel_requested_run_ids:
                    break
                suite = get_suite(suite_name)
                self.progress_stream.publish(run_id, f"{suite.title} 시작", suite_name=suite.suite_name)
                summary.suite_results.append(run_one_suite(suite, context))

            measured_metrics = {
                name: value for result in summary.suite_results for name, value in result.metrics.items()
            }
            summary.criterion_results = evaluate_pass_criteria(measured_metrics)
            summary.status = decide_run_status(summary, run_id in self._cancel_requested_run_ids)
        except Exception as error:  # noqa: BLE001 · 대상 연결 실패 등
            summary.status = RunStatus.ERROR
            summary.suite_results.append(SuiteResult("run", SuiteOutcome.ERROR, message=str(error)))
        finally:
            summary.finished_at = datetime.now(timezone.utc)
            self.run_repository.save_summary(summary)
            write_json_report(summary, self.settings.report_output_dir)
            write_html_report(summary, self.settings.report_output_dir)
            self.progress_stream.publish(
                run_id, f"끝 · {summary.status.value}", is_finished=True, final_status=summary.status.value
            )
            with self._lock:
                self._active_run_id = None
                self._active_run_ends_at = None
                self._cancel_requested_run_ids.discard(run_id)
        return summary

    def _watch_measurement_window(self, run_id: str, system_target: SystemTarget, window_sec: float) -> None:
        """측정 시간 동안 1초마다 03 화면에 진행 · 실시간 수치 전달"""
        started_at = time.monotonic()
        while run_id not in self._cancel_requested_run_ids:
            elapsed_sec = min(time.monotonic() - started_at, window_sec)
            self.progress_stream.publish(
                run_id, "측정 중",
                elapsed_sec=round(elapsed_sec, 1),
                total_sec=window_sec,
                live_metrics=read_live_metrics_or_none(system_target, run_id, elapsed_sec),
            )
            if elapsed_sec >= window_sec:
                return
            time.sleep(min(PROGRESS_TICK_SEC, window_sec - elapsed_sec))


def read_live_metrics_or_none(system_target: SystemTarget, run_id: str, elapsed_sec: float) -> LiveMetrics | None:
    try:
        return system_target.live_metrics_reader.read_live_metrics(run_id, elapsed_sec)
    except NotImplementedError:
        return None  # 실제 대상 · 아직 측정 못 함 → 화면에 "측정 전"
