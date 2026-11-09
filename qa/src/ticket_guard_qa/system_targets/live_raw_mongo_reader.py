"""원본 MongoDB(ticketguard_raw) 읽기 · 읽기 전용 계정만 · find만 · 위치 인덱스 raw_kafka_position_v1 사용 · docs/contracts.md 3-2"""
from datetime import datetime

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from ticket_guard_qa.domain.raw_event_routing import RAW_COLLECTION_NAMES, RAW_DATABASE_NAME
from ticket_guard_qa.system_targets.live_kafka_reader import decode_event
from ticket_guard_qa.system_targets.target_interfaces import RawStoredRecord

SERVER_SELECTION_TIMEOUT_MS = 5000
POSITIONS_PER_QUERY = 500
RAW_DOCUMENT_PROJECTION = {
    "_id": 0, "partition": 1, "offset": 1, "value": 1, "timestampMs": 1, "ingestedAt": 1, "routing.reason": 1,
}


class RawEventReadError(RuntimeError):
    pass


def build_position_filter(topic: str, positions: list[tuple[int, int]]) -> dict:
    offsets_by_partition: dict[int, list[int]] = {}
    for partition, offset in positions:
        offsets_by_partition.setdefault(partition, []).append(offset)
    return {"topic": topic, "$or": [
        {"partition": partition, "offset": {"$in": sorted(offsets)}}
        for partition, offsets in sorted(offsets_by_partition.items())
    ]}


def to_epoch_ms(value: object) -> float | None:
    return value.timestamp() * 1000 if isinstance(value, datetime) else None


def to_raw_stored_record(collection_name: str, document: dict) -> RawStoredRecord:
    value = document.get("value")
    timestamp_ms = document.get("timestampMs")
    return RawStoredRecord(
        collection_name=collection_name,
        partition=int(document["partition"]),
        offset=int(document["offset"]),
        event=decode_event(bytes(value)) if value is not None else None,
        timestamp_ms=int(timestamp_ms) if timestamp_ms is not None else None,
        ingested_at_ms=to_epoch_ms(document.get("ingestedAt")),
        routing_reason=(document.get("routing") or {}).get("reason"),
    )


class LiveMongoRawEventReader:
    def __init__(self, mongo_uri: str, topic: str) -> None:
        self.mongo_uri = mongo_uri
        self.topic = topic

    def find_by_positions(self, positions: list[tuple[int, int]]) -> list[RawStoredRecord]:
        """9개 컬렉션 전부 조회 · 같은 위치가 여러 컬렉션에 있으면 전부 반환 (중복 판정용)"""
        unique_positions = sorted(set(positions))
        records: list[RawStoredRecord] = []
        try:
            with MongoClient(self.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS) as client:
                database = client.get_default_database(default=RAW_DATABASE_NAME)
                for start in range(0, len(unique_positions), POSITIONS_PER_QUERY):
                    position_filter = build_position_filter(self.topic, unique_positions[start:start + POSITIONS_PER_QUERY])
                    for collection_name in RAW_COLLECTION_NAMES:
                        records += [
                            to_raw_stored_record(collection_name, document)
                            for document in database[collection_name].find(position_filter, RAW_DOCUMENT_PROJECTION)
                        ]
        except PyMongoError as error:
            raise RawEventReadError(f"원본 DB 읽기 실패 · 읽기 전용 계정 · 네트워크 확인 · {type(error).__name__}") from error
        return records
