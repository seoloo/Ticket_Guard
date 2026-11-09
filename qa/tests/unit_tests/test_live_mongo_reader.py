"""시스템 MongoDB 읽기 · QA 격리 건수가 05 화면 summary()와 분리됐는지"""
from unittest.mock import patch

import mongomock
import pytest

from ticket_guard_qa.system_targets import live_mongo_reader
from ticket_guard_qa.system_targets.live_mongo_reader import LiveMongoPipelineReader

SYSTEM_MONGO_URI = "mongodb://reader@system-host:27017/ticketguard"


def test_quarantine_count_does_not_use_dashboard_summary():
    memory_client = mongomock.MongoClient(SYSTEM_MONGO_URI)  # 기본 DB = ticketguard
    memory_client["ticketguard"].quarantine_events.insert_many([{"eventId": "e1"}, {"eventId": "e2"}])
    reader = LiveMongoPipelineReader(SYSTEM_MONGO_URI)
    with patch.object(live_mongo_reader, "MongoClient", lambda *args, **kwargs: memory_client), \
            patch.object(LiveMongoPipelineReader, "summary", side_effect=AssertionError("05 summary 호출됨")):
        assert reader.count_quarantined_events("run-test") == 2


def test_quarantine_count_needs_mongo_uri():
    with pytest.raises(ValueError):
        LiveMongoPipelineReader("").count_quarantined_events("run-test")
