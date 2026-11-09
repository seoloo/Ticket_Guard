"""관리자 전용 리더 · 실제 필드 집계와 정보 노출 경계"""
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from ticket_guard_admin.mongo_reader import AdminMongoReader, build_dashboard


def event(kind, seconds, **extra):
    return {"eventId": f"event-{seconds}-{kind}", "userId": "actual-user", "bookingAttemptId": "attempt-real",
            "occurredAt": datetime(2026, 11, 9, tzinfo=timezone.utc) + timedelta(seconds=seconds),
            "eventType": kind, "result": "success", **extra}


def test_observed_conversion_and_latency_require_matching_attempts():
    result = build_dashboard([event("queue_enter", 0), event("queue_register", 1), event("queue_admitted", 24),
                              event("booking_confirm_success", 40),
                              event("booking_confirm_success", 50, bookingAttemptId="orphan-success")])
    assert result["starts"] == 1
    assert result["completed"] == 1
    assert result["conversion"] == 100
    assert result["durations"][0] == {"label": "대기열 대기", "median": 24, "p95": 24, "count": 1}
    assert result["durations"][1]["median"] is None
    assert result["stages"][-1][1] == 2


def test_reader_projects_only_allowed_fields_and_keeps_collection_counts_separate(monkeypatch):
    client = mongomock.MongoClient("mongodb://localhost/ticketguard")
    client.ticketguard.clean_events.insert_many([
        event("queue_enter", 0, details={"password": "never-expose"}, isSimulation=False, showId="show-one"),
        event("booking_confirm_rejected", 1, result="rejected", errorCode="STALE_REQUEST", showId="show-one"),
        event("queue_enter", 2, userId="simulation-user", isSimulation=True, showId="show-two"),
    ])
    client.ticketguard.quarantine_events.insert_one({"reason": "unsupported_schema", "rawValue": b"never-expose"})
    client.ticketguard.event_metrics.insert_one({"metricType": "summary"})
    monkeypatch.setattr("ticket_guard_admin.mongo_reader.MongoClient", lambda *args, **kwargs: client)
    result = AdminMongoReader("mongodb://localhost/ticketguard").read_dashboard(show="show-one", data_kind="normal")
    assert result["matched"] == 2
    assert result["counts"] == {"clean_events": 3, "quarantine_events": 1, "event_metrics": 1}
    assert result["rejected_users"] == 1
    assert "never-expose" not in str(result)
    assert result["failures"] == [("STALE_REQUEST", 1, 1)]


def test_reader_requires_uri_and_empty_data_does_not_invent_metrics():
    with pytest.raises(ValueError):
        AdminMongoReader("")
    result = build_dashboard([])
    assert result["conversion"] is None
    assert result["users"] == []
    assert all(row["median"] is None for row in result["durations"])
