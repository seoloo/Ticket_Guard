"""가짜 대상 · 시스템 없이 시험 흐름 점검 · 규칙은 docs/contracts.md와 같게 · 화면 숫자는 예시 값"""
import math
import random
import re
import statistics
import time
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ticket_guard_qa.domain.enums import BookingOutcome, TargetKind, VerdictStage
from ticket_guard_qa.domain.models import (
    LiveMetrics,
    QuarantineRecord,
    SessionBehavior,
    SessionFeatureRecord,
    SessionKey,
    SessionVerdictRecord,
    SystemVerdicts,
    VirtualUserSessionPlan,
    VirtualUserSessionResult,
)
from ticket_guard_qa.system_targets.target_interfaces import HttpResult, StreamRecord, SystemTarget

TELEMETRY_EVENT_TYPES = frozenset({"browser_request", "resource_timing", "navigation_timing", "browser_error"})  # PR #12 · 자유 형식 details
BROWSER_EVENT_TYPES = frozenset({
    "page_enter", "page_exit", "search_change", "genre_change", "show_select",
    "schedule_select", "seat_select", "seat_cancel", "quantity_change",
}) | TELEMETRY_EVENT_TYPES
# 인증 정보 키 · 마스킹 대상 · main web/telemetry.py SECRET 기준
CREDENTIAL_KEY_PATTERN = re.compile(
    r"^(?:password|passwd|(?:current|new|confirm)[-_]?password|(?:proxy[-_]?)?authorization|(?:set[-_]?)?cookie|sessionid"
    r"|csrf(?:[-_]?token)?|x[-_]?csrf[-_]?token|csrfmiddlewaretoken|(?:x[-_]?)?api[-_]?key|(?:access|refresh|id)[-_]?token"
    r"|token|auth|secret|client[-_]?secret|answer|captcha[-_]?(?:answer|response)|g[-_]?recaptcha[-_]?response|otp)$",
    re.IGNORECASE,
)
# POST /api/events/ 규칙 · main web/views.py · web/event_schema.py (2026-11-06 · PR #12)
ALLOWED_BROWSER_EVENT_FIELDS = frozenset({
    "eventType", "eventId", "occurredAt", "pageInstanceId", "pageViewId", "showId", "scheduleId", "details",
})
KNOWN_SHOW_IDS = frozenset({"blue-hour", "open-air", "spring-concert", "city-night", "starlight", "summer-rhythm"})
SCHEDULE_ID_SUFFIX = "-evening"
PAGE_NAMES = frozenset({"login", "shows", "detail", "queue", "captcha", "select", "complete", "history", "signup"})
DETAIL_FIELDS_BY_BROWSER_EVENT_TYPE = {
    "page_enter": {"pageName", "previousPageName"},
    "page_exit": {"pageName", "previousPageName"},
    "search_change": {"queryLength", "resultCount"},
    "genre_change": {"genre"},
    "show_select": {"clickTarget"},
    "schedule_select": {"trigger", "selectedDate"},
    "seat_select": {"seatId", "selectedCount"},
    "seat_cancel": {"seatId", "selectedCount"},
    "quantity_change": {"previousQuantity", "quantity"},
}
SHOW_REQUIRED_EVENT_TYPES = frozenset({"show_select", "schedule_select", "seat_select", "seat_cancel", "quantity_change"})
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

# 가짜 룰 이름 · 실제 R1 ~ R6와 무관 · 화면에서 Mock 룰임이 보이게
MOCK_RULE_SET_VERSION = "mock-1"
MOCK_RULE_REGULAR_INTERVAL = "MOCK-R1"
MOCK_RULE_FAST_INTERVAL = "MOCK-R2"
MOCK_RULE_MULTI_SESSION = "MOCK-R3"
MOCK_RULE_INSTANT_ENTRY = "MOCK-R4"
MAX_RISK_SIGNAL_COUNT = 4

# 가짜 이벤트 토픽 · 파티션 3 · 키 = 예매 시도 번호 · docs/contracts.md 4장
FAKE_STREAM_PARTITION_COUNT = 3
FAKE_CONTRACT_USER_ID = "ticketguard"
FAKE_SEAT_CLICK_COUNT = 2
FAKE_BOOKED_SERVER_EVENT_TYPES = (
    "queue_enter", "queue_register", "queue_admitted", "captcha_success", "booking_confirm_request", "booking_confirm_success",
)

# 가짜 집계(SESSION_FEATURES) · 예시 값
FEATURE_SAMPLE_CLICK_COUNT = 20
GOLD_LATENCY_MEAN_SEC = 6.0
GOLD_LATENCY_DEVIATION_SEC = 1.5
MIN_GOLD_LATENCY_SEC = 0.5
FIXED_GOLD_LATENCY_SEC = [2.0, 3.5, 4.0, 6.5, 8.0]  # 세션 없을 때 · self_check 기대값
FIXED_DECIDED_AT = datetime(2026, 11, 3, tzinfo=timezone.utc)


def is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return isinstance(value, str)


def has_credential_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(CREDENTIAL_KEY_PATTERN.match(str(key)) or has_credential_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(has_credential_key(item) for item in value)
    return False


def find_details_error(event_type: str, details: Any) -> str | None:
    """필수 항목 누락 · 인증 정보 · pageName 값 · 목록 밖 항목은 보존(허용) · 나머지 값 범위는 Live에서 확인"""
    if not isinstance(details, dict):
        return "details 형식 오류"
    if has_credential_key(details):
        return "details 인증 정보 · 마스킹 필요"
    if event_type in TELEMETRY_EVENT_TYPES:
        return None if details else "관측 이벤트 details 비어 있음"
    if DETAIL_FIELDS_BY_BROWSER_EVENT_TYPE[event_type] - set(details):
        return "details 필수 항목 누락"
    for page_field in ("pageName", "previousPageName"):
        if page_field in details and details[page_field] not in PAGE_NAMES | ({None} if page_field == "previousPageName" else set()):
            return "details 값 오류"
    return None


def find_browser_event_error(event: dict[str, Any], now: datetime) -> str | None:
    """None = 통과 · 문자열 = 거부 이유"""
    if set(event) - ALLOWED_BROWSER_EVENT_FIELDS:
        return "허용되지 않은 필드"
    event_type = event.get("eventType")
    if event_type not in BROWSER_EVENT_TYPES:
        return "허용되지 않은 이벤트"
    if not is_uuid(event.get("eventId")):
        return "eventId 형식 오류"
    page_instance_id = event.get("pageInstanceId")
    if not isinstance(page_instance_id, str) or len(page_instance_id) > MAX_PAGE_INSTANCE_ID_LENGTH:
        return "pageInstanceId 없음"
    if not is_uuid(event.get("pageViewId")):
        return "pageViewId 형식 오류"
    try:
        occurred_at = datetime.fromisoformat(event.get("occurredAt", ""))
    except (TypeError, ValueError):
        return "occurredAt 형식 오류"
    if occurred_at.utcoffset() != timedelta(0):
        return "occurredAt UTC 아님"
    if abs((now - occurred_at).total_seconds()) > MAX_EVENT_CLOCK_SKEW_SEC:
        return "occurredAt 범위 밖"
    show_id = event.get("showId")
    if show_id is not None and show_id not in KNOWN_SHOW_IDS:
        return "없는 공연"
    schedule_id = event.get("scheduleId")
    if schedule_id is not None and (not show_id or schedule_id != show_id + SCHEDULE_ID_SUFFIX):
        return "회차 오류"
    if event_type in SHOW_REQUIRED_EVENT_TYPES and not show_id:
        return "공연 정보 없음"
    return find_details_error(event_type, event.get("details", {}))


def find_matched_mock_rules(behavior: SessionBehavior) -> tuple[str, ...]:
    """가짜 판정의 근거 · 행동 값만 봄 · 정답표 모름"""
    checks = (
        (MOCK_RULE_REGULAR_INTERVAL, behavior.click_interval_deviation_ms < behavior.click_interval_mean_ms * REGULAR_CLICK_DEVIATION_RATIO),
        (MOCK_RULE_FAST_INTERVAL, behavior.click_interval_mean_ms < FAST_CLICK_INTERVAL_MS),
        (MOCK_RULE_MULTI_SESSION, behavior.sessions_per_device > MULTI_SESSION_DEVICE_COUNT),
        (MOCK_RULE_INSTANT_ENTRY, behavior.entry_delay_after_open_ms < INSTANT_ENTRY_DELAY_MS),
    )
    return tuple(rule_id for rule_id, is_matched in checks if is_matched)


def count_risk_signals(behavior: SessionBehavior) -> int:
    return len(find_matched_mock_rules(behavior))


def judge_behavior(behavior: SessionBehavior, random_source: random.Random) -> VerdictStage:
    risk_signal_count = count_risk_signals(behavior)
    detection_probability = DETECTION_PROBABILITY_BY_RISK_SIGNAL_COUNT.get(risk_signal_count, DETECTION_PROBABILITY_HIGH_RISK)
    if random_source.random() < detection_probability:
        return VerdictStage.HOLD if risk_signal_count >= HOLD_RISK_SIGNAL_COUNT else VerdictStage.CHALLENGE
    return VerdictStage.OBSERVE if risk_signal_count else VerdictStage.NORMAL


def build_mock_feature_record(
    session_key: SessionKey, behavior: SessionBehavior, random_source: random.Random, now: datetime
) -> SessionFeatureRecord:
    """가짜 Spark 집계 · 행동 값에 흔들림을 섞어 계산 · 실제 SESSION_FEATURES와 같은 모양"""
    click_intervals_ms = [
        max(random_source.gauss(behavior.click_interval_mean_ms, behavior.click_interval_deviation_ms), 0.0)
        for _ in range(FEATURE_SAMPLE_CLICK_COUNT)
    ]
    window_end = now + timedelta(milliseconds=sum(click_intervals_ms))
    gold_latency_sec = max(random_source.gauss(GOLD_LATENCY_MEAN_SEC, GOLD_LATENCY_DEVIATION_SEC), MIN_GOLD_LATENCY_SEC)
    return SessionFeatureRecord(
        booking_attempt_id=session_key,
        entry_delay_after_open_ms=max(random_source.gauss(behavior.entry_delay_after_open_ms, behavior.entry_delay_deviation_ms), 0.0),
        click_interval_mean_ms=statistics.fmean(click_intervals_ms),
        click_interval_std_ms=statistics.pstdev(click_intervals_ms),
        sessions_per_device=behavior.sessions_per_device,
        event_count=FEATURE_SAMPLE_CLICK_COUNT + 1,  # 진입 1 + 클릭
        window_start=now,
        window_end=window_end,
        computed_at=window_end + timedelta(seconds=gold_latency_sec),
    )


def build_fixed_verdict_records(verdicts: SystemVerdicts) -> list[SessionVerdictRecord]:
    return [SessionVerdictRecord(key, stage, 0.0, (), MOCK_RULE_SET_VERSION, FIXED_DECIDED_AT) for key, stage in verdicts.items()]


@dataclass
class FakeSystemState:
    """가짜 시스템의 메모리 · 예매 API와 판정 읽기가 같이 씀"""
    random_seed: int = 20261103
    session_verdicts: SystemVerdicts = field(default_factory=dict)
    verdict_records: list[SessionVerdictRecord] = field(default_factory=list)  # SESSION_VERDICTS
    session_features: list[SessionFeatureRecord] = field(default_factory=list)  # SESSION_FEATURES
    quarantine_records: list[QuarantineRecord] = field(default_factory=list)  # QUARANTINE_EVENTS
    accepted_event_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    stream_records: list[StreamRecord] = field(default_factory=list)  # 이벤트 토픽 흉내

    def publish_to_stream(self, event: dict[str, Any], key: str) -> None:
        partition = zlib.crc32(key.encode()) % FAKE_STREAM_PARTITION_COUNT  # 같은 키 = 같은 파티션
        offset = sum(record.partition == partition for record in self.stream_records)
        self.stream_records.append(StreamRecord(partition, offset, key, int(time.time() * 1000), event))


def build_fake_event(event_type: str, user_id: str, booking_attempt_id: str | None, event_id: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "eventId": event_id or str(uuid.uuid4()), "eventType": event_type,
        "occurredAt": datetime.now(timezone.utc).isoformat(), "userId": user_id, "bookingAttemptId": booking_attempt_id,
    }


class FakeBookingApi:
    def __init__(self, state: FakeSystemState | None = None) -> None:
        self.state = state or FakeSystemState()
        self.random_source = random.Random(f"fake-system-{self.state.random_seed}")  # 정답표 시드와 분리
        self.pipeline_random_source = random.Random(f"fake-pipeline-{self.state.random_seed}")  # 판정 난수 순서 유지

    def check_health(self) -> bool:
        return True

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult:
        error_reason = find_browser_event_error(event, datetime.now(timezone.utc))
        if error_reason:
            return HttpResult(400, {"error": error_reason}, latency_ms=1.0)
        accepted_event = self.state.accepted_event_by_id.get(event["eventId"])
        if accepted_event is not None:
            if accepted_event != event:
                return HttpResult(400, {"error": "eventId 내용 충돌"}, latency_ms=1.0)
            return HttpResult(200, {"accepted": True, "state": "delivered", "duplicate": True}, latency_ms=1.0)
        self.state.accepted_event_by_id[event["eventId"]] = event
        self.state.publish_to_stream({**event, "schemaVersion": 1, "userId": FAKE_CONTRACT_USER_ID}, FAKE_CONTRACT_USER_ID)
        return HttpResult(200, {"accepted": True, "state": "delivered", "duplicate": False}, latency_ms=1.0)

    def virtual_user_capacity(self) -> int | None:
        return None

    def reset_test_data(self) -> bool:
        return True  # 대상 하나 = 실행 하나 · 이미 빈 상태

    async def run_virtual_user_session(
        self, session_plan: VirtualUserSessionPlan, open_at_monotonic: float
    ) -> VirtualUserSessionResult:
        """대기 없이 바로 판정 · 생성 순서대로 끝나서 같은 시드 = 같은 결과"""
        return self.record_session(session_plan.behavior)

    def record_session(self, behavior: SessionBehavior) -> VirtualUserSessionResult:
        session_key = SessionKey(f"attempt-{len(self.state.session_verdicts) + 1:05d}")
        stage = judge_behavior(behavior, self.random_source)
        feature_record = build_mock_feature_record(session_key, behavior, self.pipeline_random_source, datetime.now(timezone.utc))
        self.state.session_verdicts[session_key] = stage
        self.state.session_features.append(feature_record)
        self.state.verdict_records.append(SessionVerdictRecord(
            booking_attempt_id=session_key,
            stage=stage,
            score=count_risk_signals(behavior) / MAX_RISK_SIGNAL_COUNT,
            matched_rules=find_matched_mock_rules(behavior),
            rule_set_version=MOCK_RULE_SET_VERSION,
            decided_at=feature_record.computed_at,
        ))
        latency_ms = max(self.random_source.gauss(900, 350), 120)  # 예시 지연
        user_id = f"qa-user-{len(self.state.session_verdicts):04d}"
        sent_event_ids = tuple(str(uuid.uuid4()) for _ in range(FAKE_SEAT_CLICK_COUNT))
        for event_id in sent_event_ids:
            self.state.publish_to_stream(build_fake_event("seat_select", user_id, session_key, event_id), session_key)
        for event_type in FAKE_BOOKED_SERVER_EVENT_TYPES:
            self.state.publish_to_stream(build_fake_event(event_type, user_id, session_key), session_key)
        return VirtualUserSessionResult(session_key, latency_ms, is_error=False, booking_outcome=BookingOutcome.BOOKED,
                                        sent_event_ids=sent_event_ids)


class FakeVerdictReader:
    def __init__(self, state: FakeSystemState | None = None) -> None:
        self.state = state  # None = 고정 응답 14개 · self_check용

    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        if self.state is None:
            return dict(FIXED_SESSION_VERDICTS)
        return dict(self.state.session_verdicts)

    def read_verdict_records(self, run_id: str) -> list[SessionVerdictRecord]:
        if self.state is None:
            return build_fixed_verdict_records(FIXED_SESSION_VERDICTS)
        return list(self.state.verdict_records)


class AlwaysWrongVerdictReader:
    """일부러 틀리는 대상 · 봇은 NORMAL · 사람은 HOLD · self_check가 반드시 실패로 잡아야 함"""

    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        return {
            key: VerdictStage.HOLD if stage is VerdictStage.NORMAL else VerdictStage.NORMAL
            for key, stage in FIXED_SESSION_VERDICTS.items()
        }

    def read_verdict_records(self, run_id: str) -> list[SessionVerdictRecord]:
        return build_fixed_verdict_records(self.read_session_verdicts(run_id))


class FakePipelineReader:
    def __init__(self, state: FakeSystemState | None = None) -> None:
        self.state = state  # None = 고정 지연 5개 · self_check용

    def read_gold_latency_sec(self, run_id: str) -> list[float]:
        features = self.read_session_features(run_id)
        if not features:
            return list(FIXED_GOLD_LATENCY_SEC)
        return [(record.computed_at - record.window_end).total_seconds() for record in features]

    def count_quarantined_events(self, run_id: str) -> int:
        return len(self.read_quarantine_records(run_id))

    def read_session_features(self, run_id: str) -> list[SessionFeatureRecord]:
        return list(self.state.session_features) if self.state else []

    def read_quarantine_records(self, run_id: str) -> list[QuarantineRecord]:
        return list(self.state.quarantine_records) if self.state else []


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


class FakeEventStreamReader:
    def __init__(self, state: FakeSystemState) -> None:
        self.state = state

    def snapshot_end_offsets(self) -> dict[int, int]:
        return {
            partition: sum(record.partition == partition for record in self.state.stream_records)
            for partition in range(FAKE_STREAM_PARTITION_COUNT)
        }

    def read_since(self, start_offsets: dict[int, int], run_id: str) -> list[StreamRecord]:
        return [record for record in self.state.stream_records if record.offset >= start_offsets.get(record.partition, 0)]


def build_fake_system_target(random_seed: int = 20261103) -> SystemTarget:
    state = FakeSystemState(random_seed=random_seed)
    return SystemTarget(
        kind=TargetKind.FAKE,
        booking_api=FakeBookingApi(state),
        verdict_reader=FakeVerdictReader(state),
        pipeline_reader=FakePipelineReader(state),
        live_metrics_reader=FakeLiveMetricsReader(),
        process_control=FakeProcessControl(),
        event_stream_reader=FakeEventStreamReader(state),
    )
