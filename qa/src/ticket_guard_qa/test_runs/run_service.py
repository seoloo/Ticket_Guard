"""실행 시작 · 중지 · 동시 실행 잠금 · 결과 판정 · 저장 · 보고서"""
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from pymongo.database import Database

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import LiveMetrics, RunConfig, RunSummary, SuiteResult
from ticket_guard_qa.domain.pass_criteria import evaluate_pass_criteria
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileStore
from ticket_guard_qa.macro_bots.browser_capture import CAPTURE_FOLDER_NAME
from ticket_guard_qa.qa_database.archive_export import find_published_bot_versions, find_published_versions_in_use
from ticket_guard_qa.reports.html_report import write_html_report
from ticket_guard_qa.reports.json_report import write_json_report
from ticket_guard_qa.settings import Settings
from ticket_guard_qa.system_targets.target_factory import build_system_target
from ticket_guard_qa.system_targets.target_interfaces import SystemTarget
from ticket_guard_qa.test_runs.run_estimate import HISTORY_RUN_LIMIT, RunEstimate, estimate_live_run
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_repository import RunRepository
from ticket_guard_qa.test_suites.suite_interface import QaSuite, SuiteContext
from ticket_guard_qa.test_suites.suite_registry import get_suite


PROGRESS_TICK_SEC = 1.0
MOCK_TRAFFIC_TIME_LIMIT_SEC = 300  # Mock · 시간 제한 선택 없음 · 가짜 대상은 바로 끝남


REPORT_SUFFIXES = ("html", "json")  # 보고서 파일 · reports/

class RunAlreadyActiveError(Exception):
    pass


class RunDeleteError(Exception):
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
    """실제 소요 시간 기록 · 다음 Live Run 예상 시간 보정"""
    started_at = time.monotonic()
    try:
        result = suite.run(context)
    except NotImplementedError as error:
        result = SuiteResult(suite.suite_name, SuiteOutcome.SKIPPED, message=str(error))  # 실패 아님
    except Exception as error:  # noqa: BLE001 · 한 묶음 오류가 실행 전체를 멈추지 않게
        result = SuiteResult(suite.suite_name, SuiteOutcome.ERROR, message=f"{type(error).__name__}: {error}")
    return replace(result, duration_sec=round(time.monotonic() - started_at, 1))


class RunService:
    def __init__(
        self,
        settings: Settings,
        qa_database: Database,
        progress_stream: RunProgressStream,
        system_target_builder: Callable[[Settings, TargetKind], SystemTarget] = build_system_target,
    ) -> None:
        self.settings = settings
        self.qa_database = qa_database
        self.run_repository = RunRepository(qa_database)
        self.answer_key_repository = AnswerKeyRepository(qa_database)
        self.bot_profile_store = BotProfileStore(qa_database)
        self.progress_stream = progress_stream
        self.system_target_builder = system_target_builder
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._active_run_ends_at: datetime | None = None
        self._active_estimate: RunEstimate | None = None  # Live · Run 시작 때 계산 · 03 남은 시간 기준
        self._cancel_requested_run_ids: set[str] = set()

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    @property
    def active_run_remaining_sec(self) -> float | None:
        if self._active_run_ends_at is None:
            return None
        return max((self._active_run_ends_at - datetime.now(timezone.utc)).total_seconds(), 0.0)

    def estimate_run(self, run_config: RunConfig) -> RunEstimate | None:
        """Live 예상 소요 · Suite별 · Mock = None (흉내 시간 고정)"""
        if run_config.target_kind is TargetKind.FAKE:
            return None
        samples = self.run_repository.list_recent_suite_durations(TargetKind.LIVE.value, HISTORY_RUN_LIMIT, run_config.wave_size)
        return estimate_live_run(run_config, self.bot_profile_store.load_current_registry(),
                                 self.settings.queue_admission_limit, samples)

    def measurement_window_sec(self, run_config: RunConfig, run_id: str | None = None) -> float:
        """03 경과 시간 기준 · Mock = 흉내 시간 · Live = 예상 소요 합계 · 넘으면 N초 초과 표시"""
        if run_config.target_kind is TargetKind.FAKE:
            return float(self.settings.fake_run_duration_sec)  # 가짜 실행 흉내 시간 · .env로 조정
        estimate = self._active_estimate if run_id and run_id == self._active_run_id else None
        return float(round((estimate or self.estimate_run(run_config)).total_sec))

    def traffic_time_limit_sec(self, run_config: RunConfig, estimate: RunEstimate | None) -> float:
        if estimate is not None:
            return float(estimate.traffic_time_limit_sec)
        return float(run_config.duration_sec or MOCK_TRAFFIC_TIME_LIMIT_SEC)

    def run_now(self, run_config: RunConfig) -> RunSummary:
        run_id, run_config, started_at = self._reserve_run(run_config)
        return self._execute(run_id, run_config, started_at)

    def start_in_background(self, run_config: RunConfig) -> str:
        run_id, run_config, started_at = self._reserve_run(run_config)
        threading.Thread(target=self._execute, args=(run_id, run_config, started_at), daemon=True).start()
        return run_id

    def list_delete_items(self, summary: RunSummary) -> list[str]:
        """삭제 확인 창 · 이 Run과 함께 지워지는 것 · 실제로 있는 것만"""
        report_output_dir = self.settings.report_output_dir
        items = ["Run 기록 · Suite 결과 · 합격 기준 결과"]
        session_count = len(self.answer_key_repository.load(summary.run_id))
        if session_count:
            items.append(f"정답표 · 세션 {session_count:,}개")
        report_titles = [suffix.upper() for suffix in REPORT_SUFFIXES if (report_output_dir / f"{summary.run_id}.{suffix}").exists()]
        if report_titles:
            items.append(f"리포트 파일 · {' · '.join(report_titles)}")
        if (report_output_dir / CAPTURE_FOLDER_NAME / summary.run_id).exists():
            items.append("봇 C 화면 캡처")
        return items

    def delete_run(self, run_id: str) -> None:
        """Run 기록 · 정답표 · 보고서 · 캡처 삭제 · 진행 중 Run 거절 · 내보내기 기록(archive_exports)은 감사용 유지"""
        if run_id == self._active_run_id:
            raise RunDeleteError("진행 중 Run 삭제 불가 · 중지 후 삭제")
        if not self.run_repository.delete_run(run_id):  # 없는 Run · 진행 중 Run → 파일 경로에 쓰지 않음
            raise RunDeleteError("삭제할 Run 없음 · 진행 중 Run 삭제 불가")
        self.answer_key_repository.delete(run_id)
        report_output_dir = self.settings.report_output_dir
        for report_suffix in REPORT_SUFFIXES:
            (report_output_dir / f"{run_id}.{report_suffix}").unlink(missing_ok=True)
        shutil.rmtree(report_output_dir / CAPTURE_FOLDER_NAME / run_id, ignore_errors=True)

    def cancel(self, run_id: str) -> None:
        self._cancel_requested_run_ids.add(run_id)  # 묶음 사이에서 멈춤

    def _reserve_run(self, run_config: RunConfig) -> tuple[str, RunConfig, datetime]:
        # 지금 봇 버전을 기록 · 같은 버전끼리만 04 비교 · B3 · B4가 당시 설정을 다시 읽음
        current_versions = self.bot_profile_store.load_current_registry().version_number_by_actor_type()
        run_config = replace(run_config, bot_version_numbers=current_versions)
        estimate = self.estimate_run(run_config)
        with self._lock:  # 동시 실행 금지 · 02 화면 시작 잠금
            if self._active_run_id is not None:
                raise RunAlreadyActiveError(f"Run 실행 중: {self._active_run_id}")
            started_at = datetime.now(timezone.utc)
            run_id = create_run_id(started_at)
            self._active_run_id = run_id
            self._active_estimate = estimate
            self._active_run_ends_at = started_at + timedelta(seconds=self.measurement_window_sec(run_config, run_id))
        self.run_repository.create_run(run_id, run_config, started_at)
        return run_id, run_config, started_at

    def _execute(self, run_id: str, run_config: RunConfig, started_at: datetime) -> RunSummary:
        summary = RunSummary(run_id, run_config, RunStatus.RUNNING, started_at)
        estimate = self._active_estimate
        try:
            context = SuiteContext(
                run_id=run_id,
                run_config=run_config,
                system_target=self.system_target_builder(self.settings, run_config.target_kind),
                answer_key_repository=self.answer_key_repository,
                case_data_dir=self.settings.case_data_dir,
                report_progress=lambda text, **fields: self.progress_stream.publish(run_id, text, **fields),
                bot_profile_registry=self.bot_profile_store.load_registry_for_versions(run_config.bot_version_numbers),
                report_output_dir=self.settings.report_output_dir,
                traffic_time_limit_sec=self.traffic_time_limit_sec(run_config, estimate),
            )
            if estimate is not None:
                limit_title = "자동" if estimate.is_time_limit_auto else "설정"
                self.progress_stream.publish(
                    run_id, f"예상 소요 약 {format_minutes(estimate.low_sec)} ~ {format_minutes(estimate.high_sec)}"
                            f" · 트래픽 Suite 최대 {estimate.traffic_time_limit_sec}초({limit_title})")
            published_in_use = find_published_versions_in_use(
                find_published_bot_versions(self.qa_database), run_config.bot_version_numbers
            )
            if published_in_use:  # 보관본으로 내보낸 봇 버전 · 탐지율 신뢰 낮음
                self.progress_stream.publish(run_id, f"주의: 공개된 봇 버전 사용 · {' · '.join(published_in_use)} · 새 버전 저장 필요")
            window_sec = self.measurement_window_sec(run_config, run_id)
            suites_finished = threading.Event()
            if run_config.target_kind is TargetKind.FAKE:
                self._watch_measurement_window(run_id, context.system_target, window_sec, suites_finished)
            else:  # 실제 대상 · 트래픽과 함께 경과 시간 표시
                threading.Thread(
                    target=self._watch_measurement_window,
                    args=(run_id, context.system_target, window_sec, suites_finished, True), daemon=True,
                ).start()
            try:
                for suite_name in run_config.suite_names:
                    if run_id in self._cancel_requested_run_ids:
                        break
                    suite = get_suite(suite_name)
                    self.progress_stream.publish(run_id, f"{suite.title} 시작", suite_name=suite.suite_name)
                    summary.suite_results.append(run_one_suite(suite, context))
            finally:
                suites_finished.set()

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
                run_id, f"Run 종료 · {summary.status.value}", is_finished=True, final_status=summary.status.value
            )
            with self._lock:
                self._active_run_id = None
                self._active_run_ends_at = None
                self._active_estimate = None
                self._cancel_requested_run_ids.discard(run_id)
        return summary

    def _watch_measurement_window(
        self, run_id: str, system_target: SystemTarget, window_sec: float, stop_event: threading.Event,
        keeps_counting_after_window: bool = False,
    ) -> None:
        """1초마다 03 화면에 경과 시간 · 실시간 수치 전달 · 시험이 먼저 끝나면 멈춤
        Mock = 측정 시간에서 끝 · Live = Suite가 끝날 때까지 계속 (121 / 120초처럼 초과 표시)"""
        started_at = time.monotonic()
        while run_id not in self._cancel_requested_run_ids and not stop_event.is_set():
            elapsed_sec = time.monotonic() - started_at
            if not keeps_counting_after_window:
                elapsed_sec = min(elapsed_sec, window_sec)
            is_over_window = elapsed_sec > window_sec
            self.progress_stream.publish(
                run_id, "예상 시간 초과 · Suite 진행 중" if is_over_window else "측정 중",
                elapsed_sec=round(elapsed_sec, 1),
                total_sec=window_sec,
                live_metrics=read_live_metrics_or_none(system_target, run_id, min(elapsed_sec, window_sec)),
            )
            if elapsed_sec >= window_sec and not keeps_counting_after_window:
                return
            remaining_in_window = window_sec - elapsed_sec
            stop_event.wait(PROGRESS_TICK_SEC if remaining_in_window <= 0 else min(PROGRESS_TICK_SEC, remaining_in_window))


def format_minutes(seconds: float) -> str:
    return f"{round(seconds)}초" if seconds < 60 else f"{max(round(seconds / 60), 1)}분"


def read_live_metrics_or_none(system_target: SystemTarget, run_id: str, elapsed_sec: float) -> LiveMetrics | None:
    try:
        return system_target.live_metrics_reader.read_live_metrics(run_id, elapsed_sec)
    except NotImplementedError:
        return None  # 실제 대상 · 아직 측정 못 함 → 화면에 "측정 전"
