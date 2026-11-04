"""가짜 대상 · 시스템 없이 시험 흐름 점검 · 규칙은 docs/contracts.md와 같게 · 화면 숫자는 예시 값"""
import math
import random
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ticket_guard_qa.domain.enums import TargetKind, VerdictStage
from ticket_guard_qa.domain.models import (
    LiveMetrics,
    SessionBehavior,
    SessionKey,
    SystemVerdicts,
    VirtualUserSessionResult,
)
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

# 가짜 판정 · 위험 신호 개수 → 탐지 확률 · 예시 값
DETECTION_PROBABILITY_BY_RISK_SIGNAL_COUNT = {0: 0.006, 1: 0.85, 2: 0.93}
DETECTION_PROBABILITY_HIGH_RISK = 0.98
HOLD_RISK_SIGNAL_COUNT = 3
REGULAR_CLICK_DEVIATION_RATIO = 0.3
FAST_CLICK_INTERVAL_MS = 200
INSTANT_ENTRY_DELAY_MS = 100
MULTI_SESSION_DEVICE_COUNT = 2


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


def count_risk_signals(behavior: SessionBehavior) -> int:
    """가짜 판정의 근거 · 행동 값만 봄 · 정답표 모름"""
    is_regular_click = behavior.click_interval_deviation_ms < behavior.click_interval_mean_ms * REGULAR_CLICK_DEVIATION_RATIO
    return sum((
        is_regular_click,
        behavior.click_interval_mean_ms < FAST_CLICK_INTERVAL_MS,
        behavior.sessions_per_device > MULTI_SESSION_DEVICE_COUNT,
        behavior.entry_delay_after_open_ms < INSTANT_ENTRY_DELAY_MS,
    ))


def judge_behavior(behavior: SessionBehavior, random_source: random.Random) -> VerdictStage:
    risk_signal_count = count_risk_signals(behavior)
    detection_probability = DETECTION_PROBABILITY_BY_RISK_SIGNAL_COUNT.get(risk_signal_count, DETECTION_PROBABILITY_HIGH_RISK)
    if random_source.random() < detection_probability:
        return VerdictStage.HOLD if risk_signal_count >= HOLD_RISK_SIGNAL_COUNT else VerdictStage.CHALLENGE
    return VerdictStage.OBSERVE if risk_signal_count else VerdictStage.NORMAL


@dataclass
class FakeSystemState:
    """가짜 시스템의 메모리 · 예매 API와 판정 읽기가 같이 씀"""
    random_seed: int = 20261103
    session_verdicts: SystemVerdicts = field(default_factory=dict)
    accepted_event_ids: set[str] = field(default_factory=set)


class FakeBookingApi:
    def __init__(self, state: FakeSystemState | None = None) -> None:
        self.state = state or FakeSystemState()
        self.random_source = random.Random(f"fake-system-{self.state.random_seed}")  # 정답표 시드와 분리

    def check_health(self) -> bool:
        return True

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult:
        error_reason = find_browser_event_error(event, datetime.now(timezone.utc))
        if error_reason:
            return HttpResult(400, {"error": error_reason}, latency_ms=1.0)
        if event["eventId"] in self.state.accepted_event_ids:
            return HttpResult(200, {"accepted": True, "duplicate": True}, latency_ms=1.0)
        self.state.accepted_event_ids.add(event["eventId"])
        return HttpResult(200, {"accepted": True}, latency_ms=1.0)

    def start_virtual_user_session(self, behavior: SessionBehavior) -> VirtualUserSessionResult:
        session_key = SessionKey(f"attempt-{len(self.state.session_verdicts) + 1:05d}")
        self.state.session_verdicts[session_key] = judge_behavior(behavior, self.random_source)
        latency_ms = max(self.random_source.gauss(900, 350), 120)  # 예시 지연
        return VirtualUserSessionResult(session_key, latency_ms, is_error=False)


class FakeVerdictReader:
    def __init__(self, session_verdicts: SystemVerdicts | None = None) -> None:
        self.session_verdicts = session_verdicts  # None = 고정 응답 14개

    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        if self.session_verdicts is None:
            return dict(FIXED_SESSION_VERDICTS)
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


class FakeLiveMetricsReader:
    """03 화면 실시간 수치 흉내 · 실행 번호마다 같은 곡선"""

    def read_live_metrics(self, run_id: str, elapsed_sec: float) -> LiveMetrics:
        wave = math.sin(elapsed_sec / 2 + zlib.crc32(run_id.encode()) % 7)
        ramp_ratio = min(elapsed_sec / 3, 1.0)  # 처음 3초 동안 몰림
        return LiveMetrics(
            api_latency_p95_sec=round(1.7 + 0.15 * wave, 2),
            api_error_rate_percent=0.0,
            events_per_sec=round(1240 * ramp_ratio + 40 * wave),
            gold_latency_p95_sec=round(6.0 + 0.25 * elapsed_sec + 0.3 * wave, 1),
        )


class FakeProcessControl:
    def __init__(self) -> None:
        self.stopped_services: set[str] = set()

    def stop_service(self, service_name: str) -> None:
        self.stopped_services.add(service_name)

    def start_service(self, service_name: str) -> None:
        self.stopped_services.discard(service_name)


def build_fake_system_target(random_seed: int = 20261103) -> SystemTarget:
    state = FakeSystemState(random_seed=random_seed)
    return SystemTarget(
        kind=TargetKind.FAKE,
        booking_api=FakeBookingApi(state),
        verdict_reader=FakeVerdictReader(state.session_verdicts),
        pipeline_reader=FakePipelineReader(),
        live_metrics_reader=FakeLiveMetricsReader(),
        process_control=FakeProcessControl(),
    )
