"""QA DB 연결 · MongoDB QA 전용 인스턴스(qa-mongo) · 시스템 MongoDB와 서버 · 계정 · 네트워크 분리 · AGENTS.md 6장"""
from datetime import datetime, timezone
from functools import cache

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

DEFAULT_QA_DATABASE_NAME = "ticketguard_qa"
MEMORY_URL_PREFIX = "mongomock://"  # 단위 테스트 · 서버 없이 · 같은 주소 = 같은 데이터
MONGO_URL_PREFIXES = ("mongodb://", "mongodb+srv://")
SERVER_SELECTION_TIMEOUT_MS = 5000

# QA DB 컬렉션 · 정답표 · 봇 설정 포함 · 시스템 접근 금지
RUNS = "runs"  # Run 하나 = 문서 하나 · Suite 결과 · 합격 기준 포함
ANSWER_KEYS = "answer_keys"  # Run 하나 = 문서 하나 · 정답표
BOT_VERSIONS = "bot_versions"  # B2 버전 저장
ARCHIVE_EXPORTS = "archive_exports"  # QA 데이터 넘기기 기록


class QaDatabaseConfigError(ValueError):
    pass


@cache
def connect_memory_client():
    import mongomock  # dev 묶음 설치 시에만

    return mongomock.MongoClient(tz_aware=True)


def connect_qa_database(qa_database_url: str) -> Database:
    if qa_database_url.startswith(MEMORY_URL_PREFIX):
        database_name = qa_database_url.removeprefix(MEMORY_URL_PREFIX).strip("/") or DEFAULT_QA_DATABASE_NAME
        database = connect_memory_client()[database_name]
    elif qa_database_url.startswith(MONGO_URL_PREFIXES):
        client = MongoClient(qa_database_url, tz_aware=True, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS)
        database = client.get_default_database(default=DEFAULT_QA_DATABASE_NAME)
    else:
        raise QaDatabaseConfigError(
            "QA DB = MongoDB · 주소는 mongodb://… · 팀 compose 실행 시 -f qa/compose.qa-db.yml 필요 · qa/README.md"
        )
    create_indexes(database)
    return database


def create_indexes(database: Database) -> None:
    database[RUNS].create_index([("started_at", DESCENDING)])
    database[RUNS].create_index([("suite_results.suite_name", ASCENDING)])
    database[BOT_VERSIONS].create_index([("actor_type", ASCENDING), ("version_number", ASCENDING)], unique=True)


def as_utc(moment: datetime | None) -> datetime | None:
    """저장 시각은 전부 UTC · 시간대 없는 값은 UTC로 읽음"""
    if moment is None:
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
