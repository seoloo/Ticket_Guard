"""시스템 MongoDB 읽기 · 읽기 전용 계정만 · 컬렉션은 docs/contracts.md 3장"""
from typing import Any
from pymongo import MongoClient
from ticket_guard_qa.domain.models import QuarantineRecord, SessionFeatureRecord, SessionVerdictRecord, SystemVerdicts
from ticket_guard_qa.system_targets.target_interfaces import StoredOutcome

SCHEMA_NOT_READY_MESSAGE = "MongoDB 스키마 확정 전 · docs/contracts.md 3장"
QA_READ_TIMEOUT_MS = 3000
PROCESSED_EVENT_COLLECTION_NAMES = ("clean_events", "quarantine_events")  # Spark 정제 · 격리 저장

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
    def __init__(self, mongo_uri: str, topic: str = "") -> None:
        self.mongo_uri = mongo_uri
        self.topic = topic

    def read_stored_outcomes(self, positions: list[tuple[int, int]]) -> list[StoredOutcome]:
        """Spark 저장 문서 _id = 토픽:파티션:오프셋 · 정제 · 격리 컬렉션 조회 · 읽기만"""
        if not self.mongo_uri:
            raise NotImplementedError("시스템 MongoDB 읽기 미설정 · TICKET_GUARD_QA_SYSTEM_MONGO_URI · 읽기 전용 계정")
        document_ids = [f"{self.topic}:{partition}:{offset}" for partition, offset in positions]
        outcomes = []
        with MongoClient(self.mongo_uri, serverSelectionTimeoutMS=QA_READ_TIMEOUT_MS) as client:
            database = client.get_default_database()
            for collection_name in PROCESSED_EVENT_COLLECTION_NAMES:
                for document in database[collection_name].find({"_id": {"$in": document_ids}}):
                    outcomes.append(StoredOutcome(
                        int(document["partition"]), int(document["offset"]), collection_name,
                        document.get("reasonCode") or document.get("reason"),
                    ))
        return outcomes

    def find_processed_event_ids(self, event_ids: list[str]) -> list[str]:
        """정제 · 격리 컬렉션 eventId 조회 · 읽기만 · 중복 저장은 중복 그대로"""
        if not self.mongo_uri:
            raise NotImplementedError("시스템 MongoDB 읽기 미설정 · TICKET_GUARD_QA_SYSTEM_MONGO_URI · 읽기 전용 계정")
        with MongoClient(self.mongo_uri, serverSelectionTimeoutMS=QA_READ_TIMEOUT_MS) as client:
            database = client.get_default_database()
            return [
                document["eventId"]
                for collection_name in PROCESSED_EVENT_COLLECTION_NAMES
                for document in database[collection_name].find({"eventId": {"$in": event_ids}}, {"_id": 0, "eventId": 1})
            ]

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
