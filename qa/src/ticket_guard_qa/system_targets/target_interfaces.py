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


class VerdictReader(Protocol):
    def read_session_verdicts(self, run_id: str) -> SystemVerdicts: ...

    def read_verdict_records(self, run_id: str) -> list[SessionVerdictRecord]: ...  # SESSION_VERDICTS


class PipelineReader(Protocol):
    def read_gold_latency_sec(self, run_id: str) -> list[float]: ...

    def count_quarantined_events(self, run_id: str) -> int: ...

    def read_session_features(self, run_id: str) -> list[SessionFeatureRecord]: ...  # SESSION_FEATURES

    def read_quarantine_records(self, run_id: str) -> list[QuarantineRecord]: ...  # QUARANTINE_EVENTS


class LiveMetricsReader(Protocol):
    def read_live_metrics(self, run_id: str, elapsed_sec: float) -> LiveMetrics: ...  # 03 화면 · 실행 중 1초마다


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
class SystemTarget:
    kind: TargetKind
    booking_api: BookingApi
    verdict_reader: VerdictReader
    pipeline_reader: PipelineReader
    live_metrics_reader: LiveMetricsReader
    process_control: ProcessControl
    event_stream_reader: EventStreamReader | None = None  # None = 이벤트 전달 검증 건너뜀
