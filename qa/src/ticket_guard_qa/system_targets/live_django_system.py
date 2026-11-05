"""지금의 Django 시스템에 HTTP로 접속 · 시스템 코드 import 금지"""
import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from ticket_guard_qa.domain.models import (
    LiveMetrics,
    SessionKey,
    SessionVerdictRecord,
    SystemVerdicts,
    VirtualUserSessionPlan,
    VirtualUserSessionResult,
)
from ticket_guard_qa.system_targets.live_booking_client import (
    BookingFlowError,
    LiveBookingClient,
    build_test_account_username,
)
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError, HttpResult

HEALTH_CHECK_TIMEOUT_SEC = 1.5  # 화면 헤더용 · 오래 기다리지 않음


@dataclass(frozen=True)
class VirtualUserAccountPool:
    """시스템 테스트 훅 시험 계정 · qa-user-0001 ~ · 꺼져 있으면 count 0"""
    count: int
    password: str
    captcha_answer: str


@dataclass(frozen=True)
class SystemAdminAccount:
    """시험 데이터 초기화용 · 비어 있으면 초기화 건너뜀"""
    username: str = ""
    password: str = ""


class LiveDjangoBookingApi:
    def __init__(self, base_url: str, username: str, password: str,
                 test_accounts: VirtualUserAccountPool | None = None,
                 admin_account: SystemAdminAccount | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.test_accounts = test_accounts or VirtualUserAccountPool(0, "", "")
        self.admin_account = admin_account or SystemAdminAccount()
        self.transport = transport
        self.contract_runner: asyncio.Runner | None = None  # 계약 시험 · 개발 계정 한 개 · 요청 사이 로그인 유지
        self.contract_client: LiveBookingClient | None = None
        self.used_test_account_count = 0  # VU마다 다음 번호 · 계정당 진행 중 예매 1건

    def check_health(self) -> bool:
        try:
            with httpx.Client(base_url=self.base_url) as http_client:
                return http_client.get("/health/", timeout=HEALTH_CHECK_TIMEOUT_SEC).status_code == 200
        except httpx.HTTPError:
            return False

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult:
        if self.contract_runner is None:
            self.contract_runner = asyncio.Runner()
            contract_client = LiveBookingClient(self.base_url, self.transport)
            self.contract_runner.run(contract_client.login(self.username, self.password))
            self.contract_client = contract_client
        return self.contract_runner.run(self.contract_client.post_json("/api/events/", event))

    def virtual_user_capacity(self) -> int | None:
        return self.test_accounts.count - self.used_test_account_count

    def reset_test_data(self) -> bool:
        if not self.admin_account.username or not self.admin_account.password:
            return False
        asyncio.run(self._reset_as_admin())
        return True

    async def _reset_as_admin(self) -> None:
        admin_client = LiveBookingClient(self.base_url, self.transport)
        try:
            await admin_client.login(self.admin_account.username, self.admin_account.password)
            await admin_client.reset_test_data()  # 404 = 시스템 QA_RESET_ENABLED 꺼짐
        finally:
            await admin_client.close()

    async def run_virtual_user_session(
        self, session_plan: VirtualUserSessionPlan, open_at_monotonic: float
    ) -> VirtualUserSessionResult:
        """시험 계정 하나로 예매 확정까지 → 확정 못 했으면 예매 취소로 계정 반환"""
        if self.used_test_account_count >= self.test_accounts.count:
            raise AccountPoolExhaustedError(
                f"시험 계정 부족 · {self.test_accounts.count}개 · 저장소 .env QA_TEST_ACCOUNT_COUNT 확인"
            )
        self.used_test_account_count += 1
        username = build_test_account_username(self.used_test_account_count)
        client = LiveBookingClient(self.base_url, self.transport)
        try:
            flow_result = await client.run_booking_flow(
                username, self.test_accounts.password, self.test_accounts.captcha_answer, session_plan, open_at_monotonic
            )
        except BookingFlowError as error:
            return VirtualUserSessionResult(SessionKey(client.booking_attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"{error.step} · {error.error_code or error.status_code}")
        except httpx.HTTPError as error:
            return VirtualUserSessionResult(SessionKey(client.booking_attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"connection · {type(error).__name__}")
        finally:
            try:
                await client.cancel_booking()
            except httpx.HTTPError:
                pass  # 정리 실패 · 60초 뒤 시스템이 만료 처리
            await client.close()
        return VirtualUserSessionResult(
            SessionKey(flow_result.booking_attempt_id), flow_result.total_latency_ms, is_error=False,
            step_latency_ms=flow_result.step_latency_ms, booking_outcome=flow_result.booking_outcome,
            booked_seat_ids=flow_result.booked_seat_ids,
        )


class LiveDjangoVerdictReader:
    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        # TODO(판정 구현 후): 시스템 판정 결과 읽기 · AGENTS.md 11장
        raise NotImplementedError("시스템 판정 없음 · AGENTS.md 5장")

    def read_verdict_records(self, run_id: str) -> list[SessionVerdictRecord]:
        raise NotImplementedError("시스템 판정 없음 · AGENTS.md 5장")


class LiveDjangoLiveMetricsReader:
    def read_live_metrics(self, run_id: str, elapsed_sec: float) -> LiveMetrics:
        # TODO(MongoDB 연결 후): 판정 지연 · EPS · Gold 반영 시각에서 계산
        raise NotImplementedError("실시간 수치 없음 · AGENTS.md 5장")


class LiveDockerProcessControl:
    def stop_service(self, service_name: str) -> None:
        # TODO(파이프라인 연결 후): Docker SDK로 컨테이너 중지
        raise NotImplementedError("복구할 파이프라인 없음 · AGENTS.md 5장")

    def start_service(self, service_name: str) -> None:
        # TODO(파이프라인 연결 후): Docker SDK로 컨테이너 시작
        raise NotImplementedError("복구할 파이프라인 없음 · AGENTS.md 5장")
