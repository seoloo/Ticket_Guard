"""QA DB 테이블 · runs · suite_results · answer_keys · bot_versions · saved_cases"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BaseTable(DeclarativeBase):
    pass


class RunRecord(BaseTable):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    run_config: Mapped[dict] = mapped_column(JSON)
    criterion_results: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SuiteResultRecord(BaseTable):
    __tablename__ = "suite_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    suite_name: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(20))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(Text, default="")


class AnswerKeyRecord(BaseTable):
    __tablename__ = "answer_keys"  # 정답표 · 시스템 접근 금지

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    session_key: Mapped[str] = mapped_column(String(100))
    actor_type: Mapped[str] = mapped_column(String(20))


class BotVersionRecord(BaseTable):
    __tablename__ = "bot_versions"  # B2 버전 저장

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_type: Mapped[str] = mapped_column(String(20), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict] = mapped_column(JSON)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedCaseRecord(BaseTable):
    __tablename__ = "saved_cases"  # 05 "QA 사례로 저장"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_run_id: Mapped[str] = mapped_column(String(40))
    session_key: Mapped[str] = mapped_column(String(100))
    related_code: Mapped[str] = mapped_column(String(10))  # E01 ~ E22 · T1 ~ T2
    note: Mapped[str] = mapped_column(Text, default="")
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
