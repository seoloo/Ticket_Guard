"""가짜 대상 · 시스템 없이 시험 흐름 점검 · 규칙은 docs/contracts.md와 같게"""
import uuid
from datetime import datetime, timezone
from typing import Any

from ticket_guard_qa.domain.enums import TargetKind, VerdictStage
from ticket_guard_qa.domain.models import SessionKey, SystemVerdicts
from ticket_guard_qa.system_targets.target_interfaces import HttpResult, SystemTarget

BROWSER_EVENT_TYPES = frozenset({
    "page_enter", "page_exit", "search_change", "genre_change", "show_select",
    "schedule_select", "seat_select", "seat_cancel", "quantity_change",
})
KNOWN_SHOW_IDS = frozenset({"blue-hour", "open-air"})
MAX_EVENT_CLOCK_SKEW_SEC = 86_400  # 과거 · 미래 모두 24시간
MAX_PAGE_INSTANCE_ID_LENGTH = 80

# 판정 고정 응답 14개 · self_check가 정답을 알고 있음
FIXED_SESSION_VERDICTS: SystemVerdicts = {
    SessionKey("fake-01"): VerdictStage.NORMAL,
    SessionKey("fake-02"): VerdictStage.NORMAL,
    SessionKey("fake-03"): VerdictStage.NORMAL,
    SessionKey("fake-04"): VerdictStage.OBSERVE,
    SessionKey("fake-05"): VerdictStage.NORMAL,
    SessionKey("fake-06"): VerdictStage.CHALLENGE,
    SessionKey("fake-07"): VerdictStage.HOLD,
    SessionKey("fake-08"): VerdictStage.CHALLENGE,
    SessionKey("fake-09"): VerdictStage.CHALLENGE,
    SessionKey("fake-10"): VerdictStage.OBSERVE,
    SessionKey("fake-11"): VerdictStage.OBSERVE,
    SessionKey("fake-12"): VerdictStage.CHALLENGE,
    SessionKey("fake-13"): VerdictStage.HOLD,
    SessionKey("fake-14"): VerdictStage.HOLD,
}


def find_browser_event_error(event: dict[str, Any], now: datetime) -> str | None:
    """None = 통과 · 문자열 = 거부 이유"""
    if event.get("eventType") not in BROWSER_EVENT_TYPES:
        return "허용되지 않은 이벤트"
    try:
        uuid.UUID(str(event.get("eventId")))
    except ValueError:
        return "eventId 형식 오류"
    page_instance_id = event.get("pageInstanceId")
    if not isinstance(page_instance_id, str) or len(page_instance_id) > MAX_PAGE_INSTANCE_ID_LENGTH:
        return "pageInstanceId 없음"
    try:
        occurred_at = datetime.fromisoformat(event.get("occurredAt", ""))
    except (TypeError, ValueError):
        return "occurredAt 형식 오류"
    if occurred_at.tzinfo is None:
        return "occurredAt 시간대 없음"
    if abs((now - occurred_at).total_seconds()) > MAX_EVENT_CLOCK_SKEW_SEC:
        return "occurredAt 범위 밖"
    show_id = event.get("showId")
    if show_id is not None and show_id not in KNOWN_SHOW_IDS:
        return "없는 공연"
    return None


class FakeBookingApi:
    def __init__(self) -> None:
        self.accepted_event_ids: set[str] = set()

    def check_health(self) -> bool:
        return True

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult:
        error_reason = find_browser_event_error(event, datetime.now(timezone.utc))
        if error_reason:
            return HttpResult(400, {"error": error_reason}, latency_ms=1.0)
        if event["eventId"] in self.accepted_event_ids:
            return HttpResult(200, {"accepted": True, "duplicate": True}, latency_ms=1.0)
        self.accepted_event_ids.add(event["eventId"])
        return HttpResult(200, {"accepted": True}, latency_ms=1.0)


class FakeVerdictReader:
    def __init__(self, session_verdicts: SystemVerdicts | None = None) -> None:
        self.session_verdicts = dict(session_verdicts or FIXED_SESSION_VERDICTS)

    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        return dict(self.session_verdicts)


class AlwaysWrongVerdictReader:
    """일부러 틀리는 대상 · 봇은 NORMAL · 사람은 HOLD · self_check가 반드시 실패로 잡아야 함"""

    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        return {
            key: VerdictStage.HOLD if stage is VerdictStage.NORMAL else VerdictStage.NORMAL
            for key, stage in FIXED_SESSION_VERDICTS.items()
        }


class FakePipelineReader:
    def read_gold_latency_sec(self, run_id: str) -> list[float]:
        return [2.0, 3.5, 4.0, 6.5, 8.0]

    def count_quarantined_events(self, run_id: str) -> int:
        return 0


class FakeProcessControl:
    def __init__(self) -> None:
        self.stopped_services: set[str] = set()

    def stop_service(self, service_name: str) -> None:
        self.stopped_services.add(service_name)

    def start_service(self, service_name: str) -> None:
        self.stopped_services.discard(service_name)


def build_fake_system_target() -> SystemTarget:
    return SystemTarget(
        kind=TargetKind.FAKE,
        booking_api=FakeBookingApi(),
        verdict_reader=FakeVerdictReader(),
        pipeline_reader=FakePipelineReader(),
        process_control=FakeProcessControl(),
    )
