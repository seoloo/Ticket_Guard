"""QA DB 연결 · SQLite로 시작 · URL만 바꾸면 다른 DB"""
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ticket_guard_qa.qa_database.tables import BaseTable

SQLITE_URL_PREFIX = "sqlite:///"


def create_qa_database_engine(qa_database_url: str) -> Engine:
    if qa_database_url.startswith(SQLITE_URL_PREFIX) and ":memory:" not in qa_database_url:
        Path(qa_database_url.removeprefix(SQLITE_URL_PREFIX)).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(qa_database_url)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    BaseTable.metadata.create_all(engine)  # TODO(스키마 변경 생기면): Alembic 도입
    return sessionmaker(engine, expire_on_commit=False)
