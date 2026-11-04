"""시스템 MongoDB 읽기 · 읽기 전용 계정만 · 컬렉션은 docs/contracts.md 3장"""
from ticket_guard_qa.domain.models import QuarantineRecord, SessionFeatureRecord, SessionVerdictRecord, SystemVerdicts

SCHEMA_NOT_READY_MESSAGE = "MongoDB 스키마 확정 전 · docs/contracts.md 3장"


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

    def read_gold_latency_sec(self, run_id: str) -> list[float]:
        # TODO(MongoDB 연결 후): events.receivedAt → aggregates 반영 시각 차이
        raise NotImplementedError("Kafka · Spark · MongoDB 없음 · AGENTS.md 5장")

    def count_quarantined_events(self, run_id: str) -> int:
        # TODO(MongoDB 연결 후): 격리 컬렉션 건수
        raise NotImplementedError("Kafka · Spark · MongoDB 없음 · AGENTS.md 5장")

    def read_session_features(self, run_id: str) -> list[SessionFeatureRecord]:
        # TODO(스키마 확정 후): SESSION_FEATURES
        raise NotImplementedError(SCHEMA_NOT_READY_MESSAGE)

    def read_quarantine_records(self, run_id: str) -> list[QuarantineRecord]:
        # TODO(스키마 확정 후): QUARANTINE_EVENTS
        raise NotImplementedError(SCHEMA_NOT_READY_MESSAGE)
