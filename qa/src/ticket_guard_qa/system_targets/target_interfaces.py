"""시험이 기대하는 시스템의 모양 · fake / live가 같은 모양을 구현"""
from dataclasses import dataclass
from typing import Any, Protocol

from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.domain.models import (
    LiveMetrics,
    QuarantineRecord,
    SessionBehavior,
    SessionFeatureRecord,
    SessionVerdictRecord,
    SystemVerdicts,
    VirtualUserSessionResult,
)


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    body: dict[str, Any]
    latency_ms: float


class BookingApi(Protocol):
    def check_health(self) -> bool: ...

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult: ...  # POST /api/events/

    def start_virtual_user_session(self, behavior: SessionBehavior) -> VirtualUserSessionResult: ...  # 사람 / 봇 여부는 넘기지 않음


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
class SystemTarget:
    kind: TargetKind
    booking_api: BookingApi
    verdict_reader: VerdictReader
    pipeline_reader: PipelineReader
    live_metrics_reader: LiveMetricsReader
    process_control: ProcessControl
