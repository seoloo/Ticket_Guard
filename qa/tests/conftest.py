"""공용 준비물 · 테스트마다 빈 QA DB · 보고서는 임시 폴더"""
from pathlib import Path

import pytest

from ticket_guard_qa.qa_database.database import create_qa_database_engine, create_session_factory
from ticket_guard_qa.settings import Settings


@pytest.fixture
def qa_settings(tmp_path: Path) -> Settings:
    return Settings(
        qa_database_url=f"sqlite:///{(tmp_path / 'qa.db').as_posix()}",
        report_output_dir=tmp_path / "reports",
        _env_file=None,
    )


@pytest.fixture
def session_factory(qa_settings: Settings):
    return create_session_factory(create_qa_database_engine(qa_settings.qa_database_url))
