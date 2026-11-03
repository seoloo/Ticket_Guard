"""시스템 MongoDB 읽기 · 읽기 전용 계정만 · 컬렉션은 docs/contracts.md 3장"""
from ticket_guard_qa.domain.models import SystemVerdicts


class LiveMongoVerdictReader:
    def __init__(self, mongo_uri: str) -> None:
        self.mongo_uri = mongo_uri

    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        # TODO(MongoDB 연결 후): 판정 결과 컬렉션 읽기 · 저장 위치는 AGENTS.md 11장
        raise NotImplementedError("판정 저장 위치 미정 · AGENTS.md 11장")


class LiveMongoPipelineReader:
    def __init__(self, mongo_uri: str) -> None:
        self.mongo_uri = mongo_uri

    def read_gold_latency_sec(self, run_id: str) -> list[float]:
        # TODO(MongoDB 연결 후): events.receivedAt → aggregates 반영 시각 차이
        raise NotImplementedError("Kafka · Spark · MongoDB 없음 · AGENTS.md 5장")

    def count_quarantined_events(self, run_id: str) -> int:
        # TODO(MongoDB 연결 후): 격리 컬렉션 건수
        raise NotImplementedError("Kafka · Spark · MongoDB 없음 · AGENTS.md 5장")
