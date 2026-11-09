"""원본 적재 검증 · Mock 통과 · 누락 · 중복 · 오분류 · 미분류 · 원문 변형 검출 · 적재 대기 · 원본 DB 읽기"""
from datetime import datetime, timezone
from unittest.mock import patch

import mongomock
import pytest

from ticket_guard_qa.domain.enums import SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.domain.raw_event_routing import RAW_COLLECTION_NAMES, find_expected_raw_collection
from ticket_guard_qa.system_targets import live_raw_mongo_reader
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.system_targets.live_raw_mongo_reader import LiveMongoRawEventReader, build_position_filter
from ticket_guard_qa.system_targets.target_interfaces import RawStoredRecord, StreamRecord
from ticket_guard_qa.test_suites.raw_ingest import (
    RawIngestSuite,
    build_message,
    evaluate_raw_ingest,
    read_stored_records,
)
from ticket_guard_qa.test_suites.suite_interface import SuiteContext
from ticket_guard_qa.test_suites.suite_registry import SUITE_BY_NAME

TOPIC = "ticketguard.events.v1"
TIMESTAMP_MS = 1793934000000


def build_context(system_target, virtual_user_count: int = 20) -> SuiteContext:
    return SuiteContext(
        run_id="run-test",
        run_config=RunConfig(TargetKind.FAKE, ("raw_ingest",), virtual_user_count=virtual_user_count),
        system_target=system_target,
        answer_key_repository=None,
        case_data_dir=None,
        report_progress=lambda text, **fields: None,
    )


def stream_record(event_type: str, offset: int, partition: int = 0) -> StreamRecord:
    event = {"schemaVersion": 1, "eventId": f"e{offset}", "eventType": event_type, "userId": "qa-user-0001"}
    return StreamRecord(partition, offset, "a1", TIMESTAMP_MS, event)


def stored_record(record: StreamRecord, collection_name: str, latency_ms: float = 150.0, **changes) -> RawStoredRecord:
    fields = dict(collection_name=collection_name, partition=record.partition, offset=record.offset, event=record.event,
                  timestamp_ms=record.timestamp_ms, ingested_at_ms=record.timestamp_ms + latency_ms)
    return RawStoredRecord(**(fields | changes))


def run_suite_with_defect(**defect_every_nth: int):
    system_target = build_fake_system_target()
    for name, every_nth in defect_every_nth.items():
        setattr(system_target.raw_event_reader, name, every_nth)
    return RawIngestSuite(wait_sec=0).run(build_context(system_target))


def test_raw_ingest_suite_is_registered():
    assert SUITE_BY_NAME["raw_ingest"].title == "원본 적재 검증"


def test_mock_raw_ingest_passes():
    result = RawIngestSuite(wait_sec=0).run(build_context(build_fake_system_target()))
    assert result.outcome is SuiteOutcome.PASSED, result.message
    assert result.metrics["raw_ingest_qa_record_count"] == 160  # VU 20 · 좌석 클릭 2 + 서버 이벤트 6
    assert result.metrics["raw_ingest_missing_count"] == 0
    assert result.metrics["raw_ingest_duplicate_count"] == 0
    assert result.metrics["raw_ingest_misrouted_count"] == 0
    assert result.metrics["raw_ingest_altered_count"] == 0
    assert 120 <= result.metrics["raw_ingest_latency_p95_ms"] <= 160
    assert "원본 적재 160/160" in result.message


@pytest.mark.parametrize(("defect", "metric_name", "fail_title"), [
    ("drop_every_nth", "raw_ingest_missing_count", "적재 누락"),
    ("duplicate_every_nth", "raw_ingest_duplicate_count", "중복 적재"),
    ("misroute_every_nth", "raw_ingest_misrouted_count", "오분류"),
    ("alter_every_nth", "raw_ingest_altered_count", "원문 변형"),
])
def test_mock_defect_fails(defect, metric_name, fail_title):
    result = run_suite_with_defect(**{defect: 10})
    assert result.outcome is SuiteOutcome.FAILED
    assert result.metrics[metric_name] == 16
    assert result.message.startswith(f"FAIL: {fail_title} 16건")


def test_no_qa_message_fails():
    system_target = build_fake_system_target()
    result = RawIngestSuite(wait_sec=0).run(build_context(system_target, virtual_user_count=0))
    assert result.outcome is SuiteOutcome.FAILED
    assert "QA 메시지 0건" in result.message


def test_skipped_without_raw_reader():
    from dataclasses import replace

    system_target = replace(build_fake_system_target(), raw_event_reader=None)
    with pytest.raises(NotImplementedError, match="TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI"):
        RawIngestSuite().run(build_context(system_target))


def test_evaluate_finds_each_issue_and_latency():
    records = [stream_record("seat_select", 0), stream_record("queue_enter", 1), stream_record("server_request", 2),
               stream_record("booking_confirm_success", 3), stream_record("page_enter", 4), stream_record("login_success", 5)]
    stored = [
        stored_record(records[0], "behavior_events", latency_ms=100),
        stored_record(records[1], "booking_events", latency_ms=300),
        stored_record(records[1], "unclassified_events"),  # 중복
        stored_record(records[2], "behavior_events"),  # 오분류 · http_events여야 함
        stored_record(records[3], "unclassified_events", routing_reason="unknown_event_type"),  # 미분류
        stored_record(records[4], "behavior_events", event={**records[4].event, "eventType": "page_exit"}),  # 원문 변형
        # records[5] 누락
    ]
    report = evaluate_raw_ingest(records, stored)
    assert report.missing_positions == ["P0:5"]
    assert report.duplicate_positions == ["P0:1 · 2건"]
    assert report.misrouted_positions == ["P0:2 · server_request → behavior_events"]
    assert report.unclassified_positions == ["P0:3 · booking_confirm_success → unclassified_events (unknown_event_type)"]
    assert report.altered_positions == ["P0:4"]
    assert report.stored_record_count == 5 and report.issue_count == 5
    assert sorted(report.ingest_latency_ms)[:2] == [100, 150]
    message_lines = build_message(report).splitlines()
    assert message_lines[0] == "FAIL: 적재 누락 1건 · P0:5"
    assert "원본 적재 5/6" in message_lines


def test_same_offset_on_other_partition_is_separate():
    records = [stream_record("seat_select", 7, partition=0), stream_record("seat_select", 7, partition=1)]
    report = evaluate_raw_ingest(records, [stored_record(records[0], "behavior_events")])
    assert report.missing_positions == ["P1:7"]
    assert report.duplicate_positions == []


@pytest.mark.parametrize(("event", "collection_name"), [
    (None, "unclassified_events"),
    ({"schemaVersion": 3, "eventType": "seat_select"}, "unclassified_events"),
    ({"schemaVersion": True, "eventType": "seat_select"}, "unclassified_events"),  # bool은 정수 버전 아님
    ({"schemaVersion": 1, "eventType": 5}, "unclassified_events"),
    ({"schemaVersion": 1, "eventType": "not_registered"}, "unclassified_events"),
    ({"schemaVersion": 2, "eventType": "capture_chunk"}, "raw_chunks"),
    ({"schemaVersion": 1, "eventType": "server_request"}, "http_events"),
    ({"schemaVersion": 1, "eventType": "queue_admitted"}, "booking_events"),
])
def test_expected_collection_follows_routing_v1(event, collection_name):
    assert find_expected_raw_collection(event) == collection_name


class LateRawEventReader:
    """두 번째 조회부터 보임 · 적재 대기 흉내"""

    def __init__(self, records: list[RawStoredRecord]) -> None:
        self.records = records
        self.call_count = 0

    def find_by_positions(self, positions):
        self.call_count += 1
        wanted = set(positions)
        return [record for record in self.records if (record.partition, record.offset) in wanted] if self.call_count > 1 else []


def test_read_stored_records_waits_until_ingested():
    record = stream_record("seat_select", 0)
    reader = LateRawEventReader([stored_record(record, "behavior_events")])
    sleeps: list[float] = []
    stored = read_stored_records(reader, [(0, 0)], wait_sec=30, poll_interval_sec=1, sleep=sleeps.append)
    assert len(stored) == 1 and sleeps == [1]
    assert reader.call_count == 3  # 대기 · 발견 · 마지막 전체 조회


def test_read_stored_records_stops_at_deadline():
    reader = LateRawEventReader([])
    sleeps: list[float] = []
    assert read_stored_records(reader, [(0, 0)], wait_sec=0, poll_interval_sec=1, sleep=sleeps.append) == []
    assert sleeps == []


def test_position_filter_groups_offsets_by_partition():
    assert build_position_filter("s1", TOPIC, [(1, 9), (0, 3), (1, 2)]) == {"source": "s1", "topic": TOPIC, "$or": [
        {"partition": 0, "offset": {"$in": [3]}},
        {"partition": 1, "offset": {"$in": [2, 9]}},
    ]}


def test_live_reader_finds_documents_in_every_collection():
    memory_client = mongomock.MongoClient(tz_aware=True)
    database = memory_client["ticketguard_raw"]
    ingested_at = datetime(2026, 11, 8, 3, 0, 0, 250000, tzinfo=timezone.utc)
    base_document = {"source": "s1", "topic": TOPIC, "partition": 0, "offset": 4, "timestampMs": TIMESTAMP_MS,
                     "ingestedAt": ingested_at, "routing": {"version": "raw-routing-v1"}}
    database.behavior_events.insert_one({**base_document, "value": b'{"schemaVersion":1,"eventType":"seat_select"}'})
    database.unclassified_events.insert_one({**base_document, "value": b"not-json",
                                             "routing": {"version": "raw-routing-v1", "reason": "parse_failed"}})
    database.booking_events.insert_one({**base_document, "offset": 5, "value": b"{}"})  # 찾지 않는 위치
    database.http_events.insert_one({**base_document, "topic": "other.topic", "value": b"{}"})  # 다른 토픽
    database.auth_events.insert_one({**base_document, "source": "other-source", "value": b"{}"})  # 다른 원본 적재기

    with patch.object(live_raw_mongo_reader, "MongoClient", lambda *args, **kwargs: memory_client):
        stored = LiveMongoRawEventReader("mongodb://reader@raw-host:27020/ticketguard_raw", TOPIC, "s1").find_by_positions([(0, 4)])

    assert len(RAW_COLLECTION_NAMES) == 9
    by_collection = {record.collection_name: record for record in stored}
    assert set(by_collection) == {"behavior_events", "unclassified_events"}
    assert by_collection["behavior_events"].event == {"schemaVersion": 1, "eventType": "seat_select"}
    assert by_collection["behavior_events"].ingested_at_ms - TIMESTAMP_MS == pytest.approx(
        ingested_at.timestamp() * 1000 - TIMESTAMP_MS)
    assert by_collection["unclassified_events"].event is None
    assert by_collection["unclassified_events"].routing_reason == "parse_failed"
