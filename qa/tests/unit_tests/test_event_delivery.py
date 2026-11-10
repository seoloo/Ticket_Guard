"""이벤트 전달 검증 · Mock 통과 · 누락 · 중복 · 파티션 키 · 형식 오류 검출"""
from dataclasses import replace

import pytest

from ticket_guard_qa.domain.enums import BookingOutcome, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import RunConfig, SessionKey, VirtualUserSessionResult
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.system_targets.live_kafka_reader import decode_event
from ticket_guard_qa.system_targets.target_interfaces import StreamRecord
from ticket_guard_qa.test_suites.event_delivery import (
    BOOKED_SERVER_EVENT_TYPES,
    SOLD_OUT_BEFORE_CONFIRM_SERVER_EVENT_TYPES,
    SOLD_OUT_SERVER_EVENT_TYPES,
    EventDeliverySuite,
    build_message,
    evaluate_delivery,
)
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

OCCURRED_AT = "2026-11-06T03:00:00+00:00"
OCCURRED_AT_MS = 1793934000000  # OCCURRED_AT


def build_context(system_target, virtual_user_count: int = 20) -> SuiteContext:
    return SuiteContext(
        run_id="run-test",
        run_config=RunConfig(TargetKind.FAKE, ("event_delivery",), virtual_user_count=virtual_user_count),
        system_target=system_target,
        answer_key_repository=None,
        case_data_dir=None,
        report_progress=lambda text, **fields: None,
    )


def record(event_type: str, attempt_id: str | None, partition: int = 0, event_id: str | None = None,
           user_id: str = "qa-user-0001", timestamp_ms: int = OCCURRED_AT_MS + 40) -> StreamRecord:
    event = {"schemaVersion": 1, "eventId": event_id or f"{attempt_id}-{event_type}", "eventType": event_type,
             "occurredAt": OCCURRED_AT, "userId": user_id, "bookingAttemptId": attempt_id}
    return StreamRecord(partition, 0, attempt_id, timestamp_ms, event)


def booked_records(attempt_id: str, partition: int = 0) -> list[StreamRecord]:
    return [record(event_type, attempt_id, partition) for event_type in sorted(BOOKED_SERVER_EVENT_TYPES)]


def test_mock_delivery_passes():
    result = EventDeliverySuite().run(build_context(build_fake_system_target()))
    assert result.outcome is SuiteOutcome.PASSED, result.message
    assert "좌석 클릭 이벤트 40/40" in result.message
    assert result.metrics["event_delivery_missing_count"] == 0


def test_clean_stream_has_no_issues_and_latency():
    session = VirtualUserSessionResult(SessionKey("a1"), 1.0, False, booking_outcome=BookingOutcome.BOOKED,
                                       sent_event_ids=("e1", "e2"))
    records = booked_records("a1") + [record("seat_select", "a1", event_id="e1"), record("seat_select", "a1", event_id="e2")]
    report = evaluate_delivery([session], records)
    assert report.issue_count == 0
    assert report.delivery_latency_ms and max(report.delivery_latency_ms) == pytest.approx(40)


def test_missing_duplicate_partition_and_invalid_are_found():
    session = VirtualUserSessionResult(SessionKey("a1"), 1.0, False, booking_outcome=BookingOutcome.BOOKED,
                                       sent_event_ids=("e1", "e2"))
    records = [r for r in booked_records("a1") if r.event["eventType"] != "booking_confirm_success"]
    records += [record("seat_select", "a1", event_id="e1"), record("seat_select", "a1", event_id="e1"),
                record("queue_cancel", "a1", partition=2), StreamRecord(1, 5, "a1", None, None)]
    report = evaluate_delivery([session], records)
    assert report.missing_browser_event_ids == ["e2"]
    assert report.duplicate_event_ids == ["e1"]
    assert report.missing_server_events == ["a1 · booking_confirm_success"]
    assert report.partition_violation_ids == ["a1"]
    assert report.invalid_record_count == 1


def test_sold_out_needs_cancel_and_capture_is_counted_apart():
    session = VirtualUserSessionResult(SessionKey("a2"), 1.0, False, booking_outcome=BookingOutcome.SOLD_OUT)
    records = [record(event_type, "a2") for event_type in sorted(SOLD_OUT_SERVER_EVENT_TYPES - {"queue_cancel"})]
    capture = StreamRecord(0, 9, "a2", OCCURRED_AT_MS, {"schemaVersion": 2, "eventId": "c1", "eventType": "server_request",
                                                         "userId": "qa-user-0002", "bookingAttemptId": "a2"})
    report = evaluate_delivery([session], records + [capture])
    assert report.missing_server_events == ["a2 · queue_cancel"]
    assert report.capture_event_count == 1


def test_sold_out_before_confirm_needs_only_queue_and_cancel():
    session = VirtualUserSessionResult(SessionKey("a4"), 1.0, False, booking_outcome=BookingOutcome.SOLD_OUT,
                                       step_latency_ms={"captcha": 50.0, "seat_select": 0.0, "confirm": 0.0})
    records = [record(event_type, "a4") for event_type in sorted(SOLD_OUT_BEFORE_CONFIRM_SERVER_EVENT_TYPES)]
    assert evaluate_delivery([session], records).missing_server_events == []
    no_cancel = [r for r in records if r.event["eventType"] != "queue_cancel"]
    assert evaluate_delivery([session], no_cancel).missing_server_events == ["a4 · queue_cancel"]


def test_other_users_and_error_sessions_are_not_judged():
    error_session = VirtualUserSessionResult(SessionKey("a3"), 0.0, True, failed_step="verify · CAPTCHA_WRONG")
    stranger = record("queue_enter", "z9", user_id="someone")
    report = evaluate_delivery([error_session], [stranger])
    assert report.issue_count == 0 and report.qa_record_count == 0


class FailingFirstUserApi:
    """첫 VU만 접속 실패 · 나머지는 Mock 그대로"""

    def __init__(self, fake_api) -> None:
        self.fake_api = fake_api
        self.is_first = True

    def __getattr__(self, name):
        return getattr(self.fake_api, name)

    async def run_virtual_user_session(self, session_plan, open_at_monotonic):
        if self.is_first:
            self.is_first = False
            return VirtualUserSessionResult(SessionKey("failed-qa-user-0001"), 0.0, True, failed_step="connection · ConnectTimeout")
        return await self.fake_api.run_virtual_user_session(session_plan, open_at_monotonic)


def test_traffic_errors_are_reference_not_failure():
    fake_target = build_fake_system_target()
    system_target = replace(fake_target, booking_api=FailingFirstUserApi(fake_target.booking_api))
    result = EventDeliverySuite().run(build_context(system_target, virtual_user_count=5))
    assert result.outcome is SuiteOutcome.PASSED, result.message
    lines = result.message.split("\n")
    assert "참고: 트래픽 오류 VU 1명" in lines and "참고: connection · ConnectTimeout 1건" in lines
    assert lines[0] == "좌석 클릭 이벤트 8/8"


def test_delivery_failure_lines_come_first():
    session = VirtualUserSessionResult(SessionKey("a1"), 1.0, False, booking_outcome=BookingOutcome.BOOKED,
                                       sent_event_ids=("e1",))
    lines = build_message(evaluate_delivery([session], booked_records("a1")), [session]).split("\n")
    assert lines[0] == "FAIL: 좌석 클릭 이벤트 누락 1건 · e1"
    assert lines[1] == "좌석 클릭 이벤트 0/1"


def test_suite_skips_without_stream_reader():
    with pytest.raises(NotImplementedError):
        EventDeliverySuite().run(build_context(replace(build_fake_system_target(), event_stream_reader=None)))


def test_decode_event_rejects_non_json():
    assert decode_event(b"not-json") is None
    assert decode_event(b'["list"]') is None
    assert decode_event(b'{"eventId": "x"}') == {"eventId": "x"}
