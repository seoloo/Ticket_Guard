import pytest

from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunAlreadyActiveError, RunService
from ticket_guard_qa.test_suites.suite_registry import SUITE_BY_NAME


class UnfinishedSuite:
    suite_name = "unfinished_suite"
    title = "미구현 Suite"
    related_codes: tuple[str, ...] = ()

    def run(self, context):
        raise NotImplementedError("미구현")


def test_unfinished_suite_is_skipped_not_failed(qa_settings, qa_database, monkeypatch):
    monkeypatch.setitem(SUITE_BY_NAME, UnfinishedSuite.suite_name, UnfinishedSuite())
    run_service = RunService(qa_settings, qa_database, RunProgressStream())
    summary = run_service.run_now(RunConfig(TargetKind.FAKE, ("self_check", UnfinishedSuite.suite_name)))

    outcome_by_suite = {result.suite_name: result.outcome for result in summary.suite_results}
    assert outcome_by_suite == {"self_check": SuiteOutcome.PASSED, UnfinishedSuite.suite_name: SuiteOutcome.SKIPPED}
    assert summary.status is RunStatus.PASSED
    assert run_service.run_repository.get_summary(summary.run_id).status is RunStatus.PASSED
    assert (qa_settings.report_output_dir / f"{summary.run_id}.html").exists()


def test_only_one_run_at_a_time(qa_settings, qa_database):
    run_service = RunService(qa_settings, qa_database, RunProgressStream())
    run_service._active_run_id = "run-already-active"
    with pytest.raises(RunAlreadyActiveError):
        run_service.run_now(RunConfig(TargetKind.FAKE, ("self_check",)))


def test_progress_ends_with_finished_message(qa_settings, qa_database):
    progress_stream = RunProgressStream()
    summary = RunService(qa_settings, qa_database, progress_stream).run_now(RunConfig(TargetKind.FAKE, ("self_check",)))
    assert progress_stream.read_after(summary.run_id, 0)[-1].is_finished


def test_live_elapsed_time_keeps_counting_past_window_until_suites_finish(qa_settings, qa_database, monkeypatch):
    import threading

    from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
    from ticket_guard_qa.test_runs import run_service as run_service_module

    monkeypatch.setattr(run_service_module, "PROGRESS_TICK_SEC", 0.05)
    progress_stream = RunProgressStream()
    run_service = RunService(qa_settings, qa_database, progress_stream)
    suites_finished = threading.Event()
    threading.Timer(0.4, suites_finished.set).start()  # Suite가 예상(0.1초)보다 늦게 끝남
    run_service._watch_measurement_window("run-over", build_fake_system_target(), 0.1, suites_finished, True)

    messages = progress_stream.read_after("run-over", 0)
    assert max(message.elapsed_sec for message in messages) > 0.1  # 121 / 120초처럼 초과 표시
    assert messages[-1].text.startswith("예상 시간 초과")
    assert suites_finished.is_set()  # Suite 종료 = 표시 멈춤


def test_verdict_accuracy_skips_before_traffic_when_verdicts_unreadable(qa_settings, qa_database):
    from dataclasses import replace

    from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
    from ticket_guard_qa.system_targets.live_django_system import LiveDjangoVerdictReader

    class NoTrafficBookingApi:
        def __getattr__(self, name):
            raise AssertionError(f"판정 미연결인데 트래픽 전송 · {name}")

    def build_target(settings, target_kind):
        return replace(build_fake_system_target(settings.random_seed),
                       verdict_reader=LiveDjangoVerdictReader(), booking_api=NoTrafficBookingApi())

    run_service = RunService(qa_settings, qa_database, RunProgressStream(), system_target_builder=build_target)
    summary = run_service.run_now(RunConfig(TargetKind.FAKE, ("verdict_accuracy",)))
    result = summary.suite_results[0]
    assert result.outcome is SuiteOutcome.SKIPPED and "시스템 판정 없음" in result.message
    assert result.duration_sec < 5  # 트래픽 없이 바로
