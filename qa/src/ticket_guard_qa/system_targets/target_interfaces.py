"""시험이 기대하는 시스템의 모양 · fake / live가 같은 모양을 구현"""
from dataclasses import dataclass
from typing import Any, Protocol

from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.domain.models import (
    LiveMetrics,
    QuarantineRecord,
    SessionFeatureRecord,
    SessionVerdictRecord,
    SystemVerdicts,
    VirtualUserSessionPlan,
    VirtualUserSessionResult,
)


PIPELINE_SERVICE_NAME = "pipeline"  # 장애 복구 · Kafka → 정제 · 격리 저장 작업


class AccountPoolExhaustedError(RuntimeError):
    """Live 시험 계정 수보다 VU가 많음"""


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    body: dict[str, Any]
    latency_ms: float


@dataclass(frozen=True)
class InventorySnapshot:
    """좌석 선택 단계 진입 시점 재고 · 지정석 판매 목록 · 자유석 잔여 수량"""
    sold_seat_ids: frozenset[str]
    remaining_quantity: int


@dataclass(frozen=True)
class ConfirmResponse:
    """확정 요청 하나의 응답 · status_code 0 = 연결 오류"""
    status_code: int
    error_code: str | None
    booking_id: str | None  # 200일 때만
    remaining_quantity: int | None  # 409 재고 응답 본문
    latency_ms: float


@dataclass(frozen=True)
class AdmissionSample:
    """대기열 통과 구간 하나 · T1 동시 입장 측정 · 단조 시계 초 · 입장 실패면 시각 None"""
    admitted_at_sec: float | None
    released_at_sec: float | None
    wait_ms: float  # 대기열 진입 → 입장
    error: str | None = None


@dataclass(frozen=True)
class StoredOutcome:
    """토픽 메시지 하나의 정제 · 격리 저장 결과 · 위치(파티션 · 오프셋)로 연결"""
    partition: int
    offset: int
    collection_name: str  # clean_events · quarantine_events
    reason_code: str | None = None  # 격리 사유


@dataclass
class SeatContender:
    """좌석 선택 단계에서 대기 중인 VU · 동시 확정용 · handle은 구현체 전용"""
    contender_id: str  # bookingAttemptId
    inventory: InventorySnapshot
    handle: Any


class BookingApi(Protocol):
    def check_health(self) -> bool: ...

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult: ...  # POST /api/events/

    def virtual_user_capacity(self) -> int | None: ...  # 동시에 쓸 수 있는 VU 수 · None = 제한 없음

    def reset_test_data(self) -> bool: ...  # 트래픽 전 초기화 · False = 건너뜀

    async def run_virtual_user_session(
        self, session_plan: VirtualUserSessionPlan, open_at_monotonic: float
    ) -> VirtualUserSessionResult: ...  # 사람 / 봇 여부는 넘기지 않음

    # 좌석 동시성 · 선택 단계까지 준비 → 동시 확정 → 정리 · E12 · E20
    async def prepare_seat_contender(self, show_id: str) -> SeatContender: ...

    async def send_confirms(
        self, contender: SeatContender, seat_ids: tuple[str, ...], quantity: int, repeat_count: int = 1
    ) -> list[ConfirmResponse]: ...  # repeat_count 2 = 같은 확정 동시 재전송

    async def release_seat_contender(self, contender: SeatContender) -> None: ...
    async def send_confirm_with_last_sequence(
        self, contender: SeatContender, seat_ids: tuple[str, ...], quantity: int, is_same_sequence: bool
    ) -> ConfirmResponse: ...  # is_same_sequence = 직전 순번 재사용 · 오래된 요청 거부 확인
    # 부하 · T1 동시 입장 상한 · T2 요청 속도 제한
    async def hold_admitted_session(self, show_id: str, hold_sec: float) -> AdmissionSample: ...  # 대기열 진입 → 입장 → hold_sec 유지 → 이탈
    async def send_request_burst(self, request_count: int, interval_sec: float) -> list[int]: ...  # 세션 하나 연속 요청 · 상태 코드 · 0 = 연결 오류


class VerdictReader(Protocol):
    def read_session_verdicts(self, run_id: str) -> SystemVerdicts: ...

    def read_verdict_records(self, run_id: str) -> list[SessionVerdictRecord]: ...  # SESSION_VERDICTS


class PipelineReader(Protocol):
    def read_gold_latency_sec(self, run_id: str) -> list[float]: ...

    def count_quarantined_events(self, run_id: str) -> int: ...

    def read_session_features(self, run_id: str) -> list[SessionFeatureRecord]: ...  # SESSION_FEATURES

    def read_quarantine_records(self, run_id: str) -> list[QuarantineRecord]: ...  # QUARANTINE_EVENTS
    def find_processed_event_ids(self, event_ids: list[str]) -> list[str]: ...  # 정제 · 격리 저장 eventId · 중복 저장은 중복 그대로
    def read_stored_outcomes(self, positions: list[tuple[int, int]]) -> list[StoredOutcome]: ...  # 위치별 정제 · 격리 결과


class LiveMetricsReader(Protocol):
    def read_live_metrics(self, run_id: str, elapsed_sec: float) -> LiveMetrics: ...  # 03 화면 · 실행 중 1초마다


class EventInjector(Protocol):
    """이벤트 토픽 직접 주입 · 계약 시험 전용 · 시스템 파이프라인 입력 형식 검사"""

    def inject_messages(self, messages: list[tuple[str | None, bytes]]) -> list[tuple[int, int]]: ...  # (키, 값) → (파티션, 오프셋)


class ProcessControl(Protocol):
    def stop_service(self, service_name: str) -> None: ...

    def start_service(self, service_name: str) -> None: ...


@dataclass(frozen=True)
class StreamRecord:
    """이벤트 토픽 메시지 하나 · event None = JSON 해석 실패"""
    partition: int
    offset: int
    key: str | None
    timestamp_ms: int | None  # 메시지 생성 시각 (프로듀서)
    event: dict[str, Any] | None


class EventStreamReader(Protocol):
    """이벤트 토픽 읽기 전용 · 읽은 위치 저장(commit) 없음 · 다른 소비자 그룹과 공유 금지"""

    def snapshot_end_offsets(self) -> dict[int, int]: ...  # 파티션 → 현재 끝 위치 · Run 시작 직전

    def read_since(self, start_offsets: dict[int, int], run_id: str) -> list[StreamRecord]: ...


@dataclass(frozen=True)
class RawStoredRecord:
    """원본 DB 문서 하나 · 위치(파티션 · 오프셋)로 토픽 메시지와 연결 · event None = 원문 해석 실패"""
    collection_name: str
    partition: int
    offset: int
    event: dict[str, Any] | None
    timestamp_ms: int | None  # timestampMs · 메시지 생성 시각
    ingested_at_ms: float | None  # ingestedAt · 최초 적재 시각
    routing_reason: str | None = None  # 미분류 사유


class RawEventReader(Protocol):
    """원본 DB 읽기 전용 · 읽기 전용 계정만 · 쓰기 · 삭제 없음"""

    def find_by_positions(self, positions: list[tuple[int, int]]) -> list[RawStoredRecord]: ...  # (파티션, 오프셋)


@dataclass(frozen=True)
class SystemTarget:
    kind: TargetKind
    booking_api: BookingApi
    verdict_reader: VerdictReader
    pipeline_reader: PipelineReader
    live_metrics_reader: LiveMetricsReader
    process_control: ProcessControl
    event_stream_reader: EventStreamReader | None = None  # None = 이벤트 전달 검증 건너뜀
    raw_event_reader: RawEventReader | None = None  # None = 원본 적재 검증 건너뜀
    event_injector: EventInjector | None = None  # None = 토픽 계약 사례 건너뜀
