"""QA DB 옮기기 · 건수 · 시간대 · 대상에 데이터 있으면 거절"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ticket_guard_qa.qa_database.database import create_qa_database_engine, create_session_factory
from ticket_guard_qa.qa_database.database_copy import DatabaseCopyError, copy_qa_database
from ticket_guard_qa.qa_database.tables import BotVersionRecord, RunRecord

SAVED_AT = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)


def test_copy_keeps_rows_and_refuses_second_copy(tmp_path):
    source_engine = create_qa_database_engine(f"sqlite:///{(tmp_path / 'source.db').as_posix()}")
    with create_session_factory(source_engine)() as session:
        session.add(RunRecord(run_id="run-1", target_kind="fake", status="PASSED", run_config={}, started_at=SAVED_AT))
        session.add(BotVersionRecord(actor_type="BOT_A", version_number=2, profile={"clicks": 3}, saved_at=SAVED_AT))
        session.commit()
    target_engine = create_qa_database_engine(f"sqlite:///{(tmp_path / 'target.db').as_posix()}")

    copied_counts = copy_qa_database(source_engine, target_engine)
    assert (copied_counts["runs"], copied_counts["bot_versions"], copied_counts["answer_keys"]) == (1, 1, 0)
    with create_session_factory(target_engine)() as session:
        bot_version = session.scalars(select(BotVersionRecord)).one()
        assert (bot_version.version_number, bot_version.profile) == (2, {"clicks": 3})
    with pytest.raises(DatabaseCopyError):
        copy_qa_database(source_engine, target_engine)
