"""가짜 대상 · 시스템 없이 시험 흐름 점검 · 규칙은 docs/contracts.md와 같게 · 화면 숫자는 예시 값"""
import asyncio
import contextlib
import json
import math
import random
import re
import statistics
import time
import uuid
import zlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ticket_guard_qa.domain.enums import BookingOutcome, TargetKind, VerdictStage
from ticket_guard_qa.domain.raw_event_routing import find_expected_raw_collection
from ticket_guard_qa.domain.rule_sets import MOCK_RULE_SET_VERSION, find_matched_rule_ids
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
from ticket_guard_qa.system_targets.target_interfaces import (
    PIPELINE_SERVICE_NAME,
    AdmissionSample,
    ConfirmResponse,
    HttpResult,
    InventorySnapshot,
    RawStoredRecord,
    SeatContender,
    StoredOutcome,
    StreamRecord,
    SystemTarget,
)

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
MAX_RISK_SIGNAL_COUNT = 4

# 가짜 이벤트 토픽 · 파티션 3 · 키 = 예매 시도 번호 · docs/contracts.md 4장
FAKE_STREAM_PARTITION_COUNT = 3
FAKE_CONTRACT_USER_ID = "ticketguard"
FAKE_SEAT_CLICK_COUNT = 2
CLEAN_COLLECTION_NAME = "clean_events"  # 시스템 Spark 정제 저장
QUARANTINE_COLLECTION_NAME = "quarantine_events"  # 시스템 Spark 격리 저장
SUPPORTED_SCHEMA_VERSIONS = (1, 2)
FAKE_QUEUE_ADMISSION_LIMIT = 20  # T1 가짜 동시 입장 상한
FAKE_RATE_LIMIT_PER_SEC = 10  # T2 가짜 초당 요청 한도 · 1초 구간
FAKE_INGEST_LATENCY_MS = 120  # 원본 적재 지연 예시 · 배치 1초 이내
FAKE_MISROUTE_COLLECTION_NAME = "collector_events"  # QA 이벤트가 오지 않는 컬렉션 · 오분류 · 중복 흉내
FAKE_BOOKED_SERVER_EVENT_TYPES = (
    "queue_enter", "queue_register", "queue_admitted", "captcha_success", "booking_confirm_request", "booking_confirm_success",
)

# 가짜 재고 · main web/services.py 초기 상태와 같게 · 지정석 공연끼리 · 자유석 공연끼리 재고 공유
FAKE_INITIAL_SOLD_SEAT_IDS = frozenset({"A5", "B2", "B8", "D3", "D9", "F4", "F8", "H1", "H10", "I4"})
FAKE_INITIAL_REMAINING_QUANTITY = 28
FAKE_GENERAL_SHOW_IDS = frozenset({"open-air", "starlight"})
FAKE_RESERVED_SEAT_IDS = frozenset(f"{row}{number}" for row in "ABCDEFGHIJ" for number in range(1, 11))
MAX_SEATS_PER_BOOKING = 4

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
    """가짜 판정의 근거 · 행동 값만 봄 · 정답표 모름 · B2 룰 매칭 예측과 같은 규칙"""
    return find_matched_rule_ids(behavior, MOCK_RULE_SET_VERSION)


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
    sold_seat_ids: set[str] = field(default_factory=lambda: set(FAKE_INITIAL_SOLD_SEAT_IDS))
    remaining_quantity: int = FAKE_INITIAL_REMAINING_QUANTITY
    booking_count: int = 0
    is_seat_lock_broken: bool = False  # True = 확인과 차감 사이 잠금 없음 · 초과 판매 결함 흉내 · FAIL 검출 확인용
    is_queue_limit_broken: bool = False  # True = 동시 입장 상한 없음 · T1 결함 흉내
    is_rate_limit_missing: bool = False  # True = 요청 속도 제한 없음 · T2 결함 흉내
    is_pipeline_running: bool = True
    processed_event_ids: list[str] = field(default_factory=list)  # 가짜 정제 · 격리 저장
    pipeline_backlog: list[str] = field(default_factory=list)  # 중지 중 쌓인 이벤트
    clean_event_ids: set[str] = field(default_factory=set)  # 토픽 주입 정제 저장 eventId
    stored_outcomes: list[StoredOutcome] = field(default_factory=list)  # 토픽 주입 정제 · 격리 결과
    is_backlog_lost: bool = False  # True = 재시작 후 중지 중 이벤트 유실 · 장애 복구 결함 흉내
    is_checkpoint_broken: bool = False  # True = 재시작 후 처음부터 다시 처리 · 중복 저장 결함 흉내

    def process_event(self, event_id: str) -> None:
        if self.is_pipeline_running:
            self.processed_event_ids.append(event_id)
        else:
            self.pipeline_backlog.append(event_id)

    def restart_pipeline(self) -> None:
        """checkpoint 다음부터 이어서 처리"""
        if self.is_checkpoint_broken:
            self.processed_event_ids += list(self.processed_event_ids)
        if not self.is_backlog_lost:
            self.processed_event_ids += self.pipeline_backlog
        self.pipeline_backlog = []
        self.is_pipeline_running = True

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
        self.admission_slots: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None  # 실행 루프마다 새로
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
        self.state.process_event(event["eventId"])
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
        return self.record_session(session_plan.behavior, session_plan.device_key)

    def record_session(self, behavior: SessionBehavior, device_key: str = "") -> VirtualUserSessionResult:
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
                                        sent_event_ids=sent_event_ids, device_key=device_key)

    async def prepare_seat_contender(self, show_id: str) -> SeatContender:
        contender_id = f"contender-{uuid.uuid4().hex[:8]}"
        inventory = InventorySnapshot(frozenset(self.state.sold_seat_ids), self.state.remaining_quantity)
        return SeatContender(contender_id, inventory, {"show_id": show_id, "booking_id": None, "sent_sequence": 0, "accepted_sequence": 0})

    async def send_confirms(
        self, contender: SeatContender, seat_ids: tuple[str, ...], quantity: int, repeat_count: int = 1
    ) -> list[ConfirmResponse]:
        first_sequence = contender.handle["sent_sequence"] + 1
        contender.handle["sent_sequence"] += repeat_count
        return list(await asyncio.gather(*(
            self.confirm(contender, seat_ids, quantity, first_sequence + index) for index in range(repeat_count)
        )))

    async def send_confirm_with_last_sequence(
        self, contender: SeatContender, seat_ids: tuple[str, ...], quantity: int, is_same_sequence: bool
    ) -> ConfirmResponse:
        if not is_same_sequence:
            contender.handle["sent_sequence"] += 1
        return await self.confirm(contender, seat_ids, quantity, contender.handle["sent_sequence"])

    async def release_seat_contender(self, contender: SeatContender) -> None:
        return None

    def get_admission_slots(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self.admission_slots is None or self.admission_slots[0] is not loop:
            self.admission_slots = (loop, asyncio.Semaphore(FAKE_QUEUE_ADMISSION_LIMIT))
        return self.admission_slots[1]

    def admission_limit(self) -> int | None:
        return FAKE_QUEUE_ADMISSION_LIMIT  # 상한 붕괴 결함 Mock도 같은 값 · 실제 입장이 넘으면 FAIL

    async def hold_admitted_session(self, show_id: str, hold_sec: float) -> AdmissionSample:
        """상한만큼만 동시 입장 · 나머지는 빈자리 대기"""
        entered_at = time.monotonic()
        slots = contextlib.nullcontext() if self.state.is_queue_limit_broken else self.get_admission_slots()
        async with slots:
            admitted_at = time.monotonic()
            await asyncio.sleep(hold_sec)
            released_at = time.monotonic()
        return AdmissionSample(admitted_at, released_at, (admitted_at - entered_at) * 1000)

    async def send_request_burst(self, request_count: int, interval_sec: float) -> list[int]:
        """가상 시각 · 직전 1초 안 요청이 한도 이상이면 429"""
        accepted_times: list[float] = []
        status_codes = []
        for index in range(request_count):
            now = index * interval_sec
            recent_count = sum(now - accepted_time < 1.0 for accepted_time in accepted_times)
            if not self.state.is_rate_limit_missing and recent_count >= FAKE_RATE_LIMIT_PER_SEC:
                status_codes.append(429)
                continue
            accepted_times.append(now)
            status_codes.append(200)
        return status_codes

    async def confirm(self, contender: SeatContender, seat_ids: tuple[str, ...], quantity: int, sequence: int) -> ConfirmResponse:
        """main web/services.py confirm 규칙 · 이미 예매한 시도 = 같은 예매 번호 · 받은 순번 이하 = 거부 · 확인과 차감은 한 번에"""
        attempt = contender.handle
        if attempt["booking_id"]:
            return ConfirmResponse(200, None, attempt["booking_id"], None, 1.0)
        if sequence <= attempt["accepted_sequence"]:
            return ConfirmResponse(409, "STALE_REQUEST", None, None, 1.0)
        attempt["accepted_sequence"] = sequence  # 검증 실패해도 순번은 소모
        is_general = attempt["show_id"] in FAKE_GENERAL_SHOW_IDS
        if is_general and not 1 <= quantity <= MAX_SEATS_PER_BOOKING:
            return ConfirmResponse(400, "SELECTION_LIMIT", None, None, 1.0)
        if not is_general and (not 1 <= len(seat_ids) <= MAX_SEATS_PER_BOOKING or not set(seat_ids) <= FAKE_RESERVED_SEAT_IDS):
            return ConfirmResponse(400, "SELECTION_LIMIT", None, None, 1.0)
        if is_general and quantity > self.state.remaining_quantity:
            return ConfirmResponse(409, "INSUFFICIENT_STOCK", None, self.state.remaining_quantity, 1.0)
        if not is_general and self.state.sold_seat_ids.intersection(seat_ids):
            return ConfirmResponse(409, "SEAT_SOLD", None, self.state.remaining_quantity, 1.0)
        if self.state.is_seat_lock_broken:
            await asyncio.sleep(0)  # 다른 확정 요청이 같은 재고를 먼저 확인
        if is_general:
            self.state.remaining_quantity -= quantity
        else:
            self.state.sold_seat_ids.update(seat_ids)
        self.state.booking_count += 1
        attempt["booking_id"] = f"TG-FAKE{self.state.booking_count:05d}"
        return ConfirmResponse(200, None, attempt["booking_id"], None, 1.0)


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

    def read_stored_outcomes(self, positions: list[tuple[int, int]]) -> list[StoredOutcome]:
        wanted_positions = set(positions)
        return [outcome for outcome in self.state.stored_outcomes
                if (outcome.partition, outcome.offset) in wanted_positions] if self.state else []

    def find_processed_event_ids(self, event_ids: list[str]) -> list[str]:
        wanted_event_ids = set(event_ids)
        return [event_id for event_id in self.state.processed_event_ids if event_id in wanted_event_ids] if self.state else []


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


def normalize_fake_message(value: bytes, clean_event_ids: set[str]) -> tuple[str, str | None]:
    """가짜 정제 · 격리 · docs/contracts.md 3-4 격리 사유 코드 · (컬렉션, 사유)"""
    try:
        event = json.loads(value)
    except (ValueError, UnicodeDecodeError):
        return QUARANTINE_COLLECTION_NAME, "PARSE_ERROR"
    if not isinstance(event, dict):
        return QUARANTINE_COLLECTION_NAME, "PARSE_ERROR"
    if type(event.get("schemaVersion")) is not int or event["schemaVersion"] not in SUPPORTED_SCHEMA_VERSIONS:
        return QUARANTINE_COLLECTION_NAME, "UNSUPPORTED_SCHEMA"
    if not isinstance(event.get("eventId"), str) or not isinstance(event.get("eventType"), str):
        return QUARANTINE_COLLECTION_NAME, "MISSING_FIELD"
    if event["eventId"] in clean_event_ids:
        return QUARANTINE_COLLECTION_NAME, "DUPLICATE_EVENT_ID"
    clean_event_ids.add(event["eventId"])
    return CLEAN_COLLECTION_NAME, None


class FakeEventInjector:
    """토픽 주입 흉내 · 받은 즉시 가짜 정제 · 격리 저장"""

    def __init__(self, state: FakeSystemState) -> None:
        self.state = state

    def inject_messages(self, messages: list[tuple[str | None, bytes]]) -> list[tuple[int, int]]:
        positions = []
        for key, value in messages:
            partition = zlib.crc32((key or "").encode()) % FAKE_STREAM_PARTITION_COUNT
            offset = sum(record.partition == partition for record in self.state.stream_records)
            self.state.stream_records.append(StreamRecord(partition, offset, key, int(time.time() * 1000), None))
            collection_name, reason_code = normalize_fake_message(value, self.state.clean_event_ids)
            self.state.stored_outcomes.append(StoredOutcome(partition, offset, collection_name, reason_code))
            positions.append((partition, offset))
        return positions


class FakeProcessControl:
    """가짜 파이프라인 중지 · 시작 · state 없으면 이름만 기록"""

    def __init__(self, state: FakeSystemState | None = None) -> None:
        self.state = state
        self.stopped_services: set[str] = set()

    def stop_service(self, service_name: str) -> None:
        self.stopped_services.add(service_name)
        if self.state and service_name == PIPELINE_SERVICE_NAME:
            self.state.is_pipeline_running = False

    def start_service(self, service_name: str) -> None:
        self.stopped_services.discard(service_name)
        if self.state and service_name == PIPELINE_SERVICE_NAME:
            self.state.restart_pipeline()


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


class FakeRawEventReader:
    """가짜 원본 DB · 가짜 토픽 메시지를 raw-routing-v1대로 보관한 것처럼 · *_every_nth = n번째마다 결함 흉내 · FAIL 검출 확인용"""

    def __init__(self, state: FakeSystemState) -> None:
        self.state = state
        self.drop_every_nth = 0  # 적재 누락
        self.duplicate_every_nth = 0  # 다른 컬렉션에 한 번 더
        self.misroute_every_nth = 0  # 다른 컬렉션에 보관
        self.alter_every_nth = 0  # 원문 변형

    def find_by_positions(self, positions: list[tuple[int, int]]) -> list[RawStoredRecord]:
        wanted_positions = set(positions)
        stored_records: list[RawStoredRecord] = []
        for index, record in enumerate(self.state.stream_records, start=1):
            if (record.partition, record.offset) not in wanted_positions or is_every_nth(index, self.drop_every_nth):
                continue
            collection_name = find_expected_raw_collection(record.event)
            event = record.event
            if is_every_nth(index, self.misroute_every_nth):
                collection_name = FAKE_MISROUTE_COLLECTION_NAME
            if is_every_nth(index, self.alter_every_nth) and event is not None:
                event = {**event, "eventType": "altered"}
            stored_record = RawStoredRecord(
                collection_name=collection_name, partition=record.partition, offset=record.offset, event=event,
                timestamp_ms=record.timestamp_ms,
                ingested_at_ms=record.timestamp_ms + FAKE_INGEST_LATENCY_MS + (record.offset % 5) * 10
                if record.timestamp_ms is not None else None,
            )
            stored_records.append(stored_record)
            if is_every_nth(index, self.duplicate_every_nth):
                stored_records.append(replace(stored_record, collection_name=FAKE_MISROUTE_COLLECTION_NAME))
        return stored_records


def is_every_nth(index: int, every_nth: int) -> bool:
    return every_nth > 0 and index % every_nth == 0


def build_fake_system_target(random_seed: int = 20261103) -> SystemTarget:
    state = FakeSystemState(random_seed=random_seed)
    return SystemTarget(
        kind=TargetKind.FAKE,
        booking_api=FakeBookingApi(state),
        verdict_reader=FakeVerdictReader(state),
        pipeline_reader=FakePipelineReader(state),
        live_metrics_reader=FakeLiveMetricsReader(),
        process_control=FakeProcessControl(state),
        event_stream_reader=FakeEventStreamReader(state),
        raw_event_reader=FakeRawEventReader(state),
        event_injector=FakeEventInjector(state),
    )
