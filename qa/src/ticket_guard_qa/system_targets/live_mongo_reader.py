"""시스템 MongoDB 읽기 · 읽기 전용 계정만 · 컬렉션은 docs/contracts.md 3장"""
from typing import Any
from pymongo import MongoClient
from ticket_guard_qa.domain.models import QuarantineRecord, SessionFeatureRecord, SessionVerdictRecord, SystemVerdicts

SCHEMA_NOT_READY_MESSAGE = "MongoDB 스키마 확정 전 · docs/contracts.md 3장"
QA_READ_TIMEOUT_MS = 3000

class LiveMongoVerdictReader:
    def __init__(self, mongo_uri: str) -> None:
        self.mongo_uri = mongo_uri

    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        # TODO(MongoDB 연결 후): 판정 결과 컬렉션 읽기 · 저장 위치는 AGENTS.md 11장
        raise NotImplementedError("판정 저장 위치 미정 · AGENTS.md 11장")

    def read_verdict_records(self, run_id: str) -> list[SessionVerdictRecord]:
        # TODO(스키마 확정 후): SESSION_VERDICTS · 읽기 전용 계정
        raise NotImplementedError(SCHEMA_NOT_READY_MESSAGE)


class LiveMongoPipelineReader:
    def __init__(self, mongo_uri: str) -> None:
        self.mongo_uri = mongo_uri

    def summary(self) -> dict[str, Any]:
        """Read dashboard metrics without mutating the system database."""
        if not self.mongo_uri:
            raise ValueError("system_mongo_uri is not configured")
        with MongoClient(self.mongo_uri, serverSelectionTimeoutMS=3000, readPreference='secondaryPreferred') as client:
            database = client.get_default_database()
            clean = database.clean_events.count_documents({})
            quarantine = database.quarantine_events.count_documents({})
            metrics = list(database.event_metrics.find({}, {'_id': 0}).sort('eventType', 1))
        return {
            'clean_events': clean,
            'quarantine_events': quarantine,
            'metrics': metrics,
        }

    def read_gold_latency_sec(self, run_id: str) -> list[float]:
        # TODO(MongoDB 연결 후): events.receivedAt → aggregates 반영 시각 차이
        raise NotImplementedError("Kafka · Spark · MongoDB 없음 · AGENTS.md 5장")

    def count_quarantined_events(self, run_id: str) -> int:
        """QA 시험용 · 05 화면 summary()와 분리 · summary 반환 모양이 바뀌어도 영향 없음"""
        if not self.mongo_uri:
            raise ValueError("system_mongo_uri is not configured")
        with MongoClient(self.mongo_uri, serverSelectionTimeoutMS=QA_READ_TIMEOUT_MS) as client:
            # TODO(Run 구분 필드 확정 후): run_id 범위로 좁히기 · 지금은 전체 건수
            return int(client.get_default_database().quarantine_events.count_documents({}))

    def read_session_features(self, run_id: str) -> list[SessionFeatureRecord]:
        # TODO(스키마 확정 후): SESSION_FEATURES
        raise NotImplementedError(SCHEMA_NOT_READY_MESSAGE)

    def read_quarantine_records(self, run_id: str) -> list[QuarantineRecord]:
        # TODO(스키마 확정 후): QUARANTINE_EVENTS
        raise NotImplementedError(SCHEMA_NOT_READY_MESSAGE)
