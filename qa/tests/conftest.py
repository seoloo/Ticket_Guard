"""공용 준비물 · 테스트마다 빈 QA DB · 보고서는 임시 폴더"""
from pathlib import Path

import pytest

from ticket_guard_qa.macro_bots.bot_catalog import replace_custom_bot_types
from ticket_guard_qa.qa_database.database import connect_qa_database
from ticket_guard_qa.settings import Settings


@pytest.fixture(autouse=True)
def reset_custom_bot_types():
    """화면에서 추가한 봇 유형 목록은 프로세스 공용 · 테스트끼리 섞이지 않게 비움"""
    replace_custom_bot_types(())
    yield
    replace_custom_bot_types(())


@pytest.fixture
def qa_settings(tmp_path: Path) -> Settings:
    return Settings(
        qa_database_url=f"mongomock://qa_{tmp_path.name}",  # 테스트마다 빈 메모리 DB
        report_output_dir=tmp_path / "reports",
        fake_run_duration_sec=0,  # 테스트는 기다리지 않음
        _env_file=None,
    )


@pytest.fixture
def qa_database(qa_settings: Settings):
    return connect_qa_database(qa_settings.qa_database_url)
