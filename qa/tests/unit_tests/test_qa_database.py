"""QA DB 연결 · MongoDB 주소만 · 예전 SQLite 주소는 안내와 함께 거절"""
from datetime import datetime, timezone

import pytest

from ticket_guard_qa.domain.enums import RunStatus, TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.qa_database.database import QaDatabaseConfigError, as_utc, connect_qa_database
from ticket_guard_qa.test_runs.run_repository import RunRepository


def test_sqlite_url_is_rejected_with_compose_hint():
    with pytest.raises(QaDatabaseConfigError, match="compose.qa-db.yml"):
        connect_qa_database("sqlite:////qa/qa_data/qa.db")


def test_unfinished_run_is_marked_error_on_restart(qa_database):
    repository = RunRepository(qa_database)
    started_at = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
    repository.create_run("run-crashed", RunConfig(TargetKind.FAKE, ("self_check",)), started_at)
    repository.mark_unfinished_runs_as_error(started_at)
    summary = repository.get_summary("run-crashed")
    assert (summary.status, summary.started_at) == (RunStatus.ERROR, started_at)
    assert repository.list_recent_run_ids() == ["run-crashed"]


def test_naive_time_is_read_as_utc():
    assert as_utc(datetime(2026, 11, 6, 3, 0)) == datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
