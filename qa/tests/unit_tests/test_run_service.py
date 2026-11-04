import pytest

from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunAlreadyActiveError, RunService


def test_unfinished_suite_is_skipped_not_failed(qa_settings, session_factory):
    run_service = RunService(qa_settings, session_factory, RunProgressStream())
    summary = run_service.run_now(RunConfig(TargetKind.FAKE, ("self_check", "seat_concurrency")))

    outcome_by_suite = {result.suite_name: result.outcome for result in summary.suite_results}
    assert outcome_by_suite == {"self_check": SuiteOutcome.PASSED, "seat_concurrency": SuiteOutcome.SKIPPED}
    assert summary.status is RunStatus.PASSED
    assert run_service.run_repository.get_summary(summary.run_id).status is RunStatus.PASSED
    assert (qa_settings.report_output_dir / f"{summary.run_id}.html").exists()


def test_only_one_run_at_a_time(qa_settings, session_factory):
    run_service = RunService(qa_settings, session_factory, RunProgressStream())
    run_service._active_run_id = "run-already-active"
    with pytest.raises(RunAlreadyActiveError):
        run_service.run_now(RunConfig(TargetKind.FAKE, ("self_check",)))


def test_progress_ends_with_finished_message(qa_settings, session_factory):
    progress_stream = RunProgressStream()
    summary = RunService(qa_settings, session_factory, progress_stream).run_now(RunConfig(TargetKind.FAKE, ("self_check",)))
    assert progress_stream.read_after(summary.run_id, 0)[-1].is_finished
