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
