"""QA DB 옮기기 · SQLite → PostgreSQL · 대상이 비어 있을 때만 · 원본은 그대로"""
from datetime import datetime, timezone

from sqlalchemy import Engine, func, insert, select, text

from ticket_guard_qa.qa_database.tables import BaseTable


class DatabaseCopyError(RuntimeError):
    """대상에 이미 데이터가 있음 · 덮어쓰지 않음"""


def with_utc_datetimes(row: dict) -> dict:
    """SQLite는 시간대를 버림 · 저장 값은 전부 UTC"""
    return {
        name: value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value
        for name, value in row.items()
    }


def count_target_rows(target_engine: Engine) -> int:
    with target_engine.connect() as connection:
        return sum(
            connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in BaseTable.metadata.sorted_tables
        )


def copy_qa_database(source_engine: Engine, target_engine: Engine) -> dict[str, int]:
    """테이블별 복사 건수 · 외래 키 순서대로 · 한 트랜잭션"""
    BaseTable.metadata.create_all(target_engine)
    existing_row_count = count_target_rows(target_engine)
    if existing_row_count:
        raise DatabaseCopyError(f"대상 QA DB에 이미 {existing_row_count}건 · 덮어쓰지 않음")
    copied_counts = {}
    with source_engine.connect() as source, target_engine.begin() as target:
        for table in BaseTable.metadata.sorted_tables:
            rows = [with_utc_datetimes(dict(row._mapping)) for row in source.execute(select(table))]
            if rows:
                target.execute(insert(table), rows)
            copied_counts[table.name] = len(rows)
        if target_engine.dialect.name == "postgresql":
            for table in BaseTable.metadata.sorted_tables:
                for column in table.primary_key.columns:
                    if column.autoincrement is True:  # 번호 자동 증가 · 옮긴 마지막 번호 다음부터
                        target.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{column.name}'),"
                            f" COALESCE(MAX({column.name}), 1), MAX({column.name}) IS NOT NULL) FROM {table.name}"
                        ))
    return copied_counts
