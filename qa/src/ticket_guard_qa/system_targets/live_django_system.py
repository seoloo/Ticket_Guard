"""지금의 Django 시스템에 HTTP로 접속 · 시스템 코드 import 금지"""
import asyncio
import time
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
from ticket_guard_qa.system_targets.target_interfaces import (
    AccountPoolExhaustedError,
    AdmissionSample,
    ConfirmResponse,
    HttpResult,
    InventorySnapshot,
    SeatContender,
)

ADMISSION_POLL_INTERVAL_SEC = 0.5  # T1 입장 시각 정밀도
BURST_REQUEST_PATH = "/"  # T2 · 로그인 사용자 공연 목록 화면
DOCKER_API_BASE_URL = "http://docker"  # 소켓 연결 · 호스트 이름 무시
DOCKER_ACTION_TIMEOUT_SEC = 30.0
DOCKER_ACTION_OK_STATUS_CODES = (204, 304)  # 304 = 이미 그 상태
HEALTH_CHECK_TIMEOUT_SEC = 1.5  # 화면 헤더용 · 오래 기다리지 않음
BOOKING_ID_PATH_PREFIX = "/complete/"  # 확정 200 응답 redirect · /complete/TG-…/


def read_booking_id(body: dict[str, Any]) -> str | None:
    redirect = body.get("redirect") or ""
    if not redirect.startswith(BOOKING_ID_PATH_PREFIX):
        return None
    return redirect.removeprefix(BOOKING_ID_PATH_PREFIX).strip("/") or None


def to_confirm_response(result: HttpResult) -> ConfirmResponse:
    remaining = result.body.get("remaining")
    return ConfirmResponse(
        status_code=result.status_code,
        error_code=None if result.status_code == 200 else result.body.get("code"),
        booking_id=read_booking_id(result.body) if result.status_code == 200 else None,
        remaining_quantity=remaining if isinstance(remaining, int) else None,
        latency_ms=result.latency_ms,
    )


@dataclass
class LiveContenderHandle:
    client: LiveBookingClient
    account_number: int


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
        self.issued_account_count = 0  # 처음 쓰는 계정 번호
        self.free_account_numbers: list[int] = []  # 정리 끝난 계정 · 다시 사용 · 계정당 진행 중 예매 1건

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
        return self.test_accounts.count - self.issued_account_count + len(self.free_account_numbers)

    def acquire_account_number(self) -> int:
        if self.free_account_numbers:
            return self.free_account_numbers.pop()
        if self.issued_account_count >= self.test_accounts.count:
            raise AccountPoolExhaustedError(
                f"시험 계정 부족 · {self.test_accounts.count}개 · 저장소 .env QA_TEST_ACCOUNT_COUNT 확인"
            )
        self.issued_account_count += 1
        return self.issued_account_count

    async def release_client(self, client: LiveBookingClient, account_number: int) -> None:
        """예매 취소로 진행 중 예매 정리 → 계정 반환 · 정리 실패 계정은 이번 Run에서 다시 쓰지 않음"""
        try:
            await client.cancel_booking()
            self.free_account_numbers.append(account_number)
        except httpx.HTTPError:
            pass  # 60초 뒤 시스템이 만료 처리
        finally:
            await client.close()

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
        account_number = self.acquire_account_number()
        username = build_test_account_username(account_number)
        client = LiveBookingClient(self.base_url, self.transport)
        try:
            flow_result = await client.run_booking_flow(
                username, self.test_accounts.password, self.test_accounts.captcha_answer, session_plan, open_at_monotonic
            )
        except BookingFlowError as error:
            return VirtualUserSessionResult(SessionKey(client.booking_attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"{error.step} · {error.error_code or error.status_code}",
                                            sent_event_ids=tuple(client.sent_event_ids))
        except httpx.HTTPError as error:
            return VirtualUserSessionResult(SessionKey(client.booking_attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"connection · {type(error).__name__}",
                                            sent_event_ids=tuple(client.sent_event_ids))
        finally:
            await self.release_client(client, account_number)
        return VirtualUserSessionResult(
            SessionKey(flow_result.booking_attempt_id), flow_result.total_latency_ms, is_error=False,
            step_latency_ms=flow_result.step_latency_ms, booking_outcome=flow_result.booking_outcome,
            booked_seat_ids=flow_result.booked_seat_ids, sent_event_ids=tuple(client.sent_event_ids),
        )


    async def prepare_seat_contender(self, show_id: str) -> SeatContender:
        """시험 계정 하나 → 좌석 선택 단계 · 실패해도 계정 정리"""
        account_number = self.acquire_account_number()
        client = LiveBookingClient(self.base_url, self.transport)
        try:
            entered = await client.enter_seat_selection(
                build_test_account_username(account_number), self.test_accounts.password,
                self.test_accounts.captcha_answer, show_id,
            )
        except (BookingFlowError, httpx.HTTPError):
            await self.release_client(client, account_number)
            raise
        inventory = InventorySnapshot(frozenset(entered.body.get("sold") or ()), int(entered.body.get("remaining") or 0))
        return SeatContender(client.booking_attempt_id or "", inventory, LiveContenderHandle(client, account_number))

    async def send_confirms(
        self, contender: SeatContender, seat_ids: tuple[str, ...], quantity: int, repeat_count: int = 1
    ) -> list[ConfirmResponse]:
        """같은 예매 시도에서 확정 repeat_count번 동시 전송 · 순서 번호는 각각 증가 (더블 클릭)"""
        client = contender.handle.client
        first_sequence = client.confirm_sequence + 1
        client.confirm_sequence += repeat_count
        results = await asyncio.gather(*(
            client.post_confirm(list(seat_ids), quantity, first_sequence + index) for index in range(repeat_count)
        ), return_exceptions=True)
        responses = []
        for result in results:
            if isinstance(result, httpx.HTTPError):
                responses.append(ConfirmResponse(0, f"connection · {type(result).__name__}", None, None, 0.0))
            elif isinstance(result, BaseException):
                raise result
            else:
                responses.append(to_confirm_response(result))
        return responses

    async def release_seat_contender(self, contender: SeatContender) -> None:
        await self.release_client(contender.handle.client, contender.handle.account_number)

    async def send_confirm_with_last_sequence(
        self, contender: SeatContender, seat_ids: tuple[str, ...], quantity: int, is_same_sequence: bool
    ) -> ConfirmResponse:
        client = contender.handle.client
        if not is_same_sequence:
            client.confirm_sequence += 1
        try:
            return to_confirm_response(await client.post_confirm(list(seat_ids), quantity, client.confirm_sequence))
        except httpx.HTTPError as error:
            return ConfirmResponse(0, f"connection · {type(error).__name__}", None, None, 0.0)

    async def hold_admitted_session(self, show_id: str, hold_sec: float) -> AdmissionSample:
        """시험 계정 하나 → 대기열 → 입장(보안문자 단계) 시각 기록 → hold_sec 유지 → 예매 취소로 이탈"""
        account_number = self.acquire_account_number()
        client = LiveBookingClient(self.base_url, self.transport)
        entered_at = time.monotonic()
        try:
            await client.login(build_test_account_username(account_number), self.test_accounts.password)
            await client.start_booking(show_id)
            entered_at = time.monotonic()
            await client.wait_for_admission(ADMISSION_POLL_INTERVAL_SEC)
            admitted_at = time.monotonic()
            await asyncio.sleep(hold_sec)
            return AdmissionSample(admitted_at, time.monotonic(), (admitted_at - entered_at) * 1000)
        except BookingFlowError as error:
            return AdmissionSample(None, None, 0.0, f"{error.step} · {error.error_code or error.status_code}")
        except httpx.HTTPError as error:
            return AdmissionSample(None, None, 0.0, f"connection · {type(error).__name__}")
        finally:
            await self.release_client(client, account_number)

    async def send_request_burst(self, request_count: int, interval_sec: float) -> list[int]:
        """로그인한 세션 하나로 공연 목록 화면 연속 요청 · 429 = 요청 속도 제한"""
        account_number = self.acquire_account_number()
        client = LiveBookingClient(self.base_url, self.transport)
        status_codes = []
        try:
            await client.login(build_test_account_username(account_number), self.test_accounts.password)
            for index in range(request_count):
                if index and interval_sec:
                    await asyncio.sleep(interval_sec)
                try:
                    status_codes.append((await client.http_client.get(BURST_REQUEST_PATH)).status_code)
                except httpx.HTTPError:
                    status_codes.append(0)
        except (BookingFlowError, httpx.HTTPError):
            status_codes += [0] * (request_count - len(status_codes))
        finally:
            await self.release_client(client, account_number)
        return status_codes


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
    """Docker Engine API · 소켓으로 컨테이너 중지 · 시작 · 이름 미설정 서비스 = 건너뜀"""

    def __init__(self, container_name_by_service: dict[str, str], socket_path: str,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.container_name_by_service = {service: name for service, name in container_name_by_service.items() if name}
        self.socket_path = socket_path
        self.transport = transport

    def stop_service(self, service_name: str) -> None:
        self.send_container_action(service_name, "stop")

    def start_service(self, service_name: str) -> None:
        self.send_container_action(service_name, "start")

    def send_container_action(self, service_name: str, action: str) -> None:
        container_name = self.container_name_by_service.get(service_name)
        if not container_name:
            raise NotImplementedError(f"{service_name} 컨테이너 이름 미설정 · TICKET_GUARD_QA_PIPELINE_CONTAINER_NAME · Docker 소켓 연결")
        transport = self.transport or httpx.HTTPTransport(uds=self.socket_path)
        with httpx.Client(base_url=DOCKER_API_BASE_URL, transport=transport, timeout=DOCKER_ACTION_TIMEOUT_SEC) as client:
            response = client.post(f"/containers/{container_name}/{action}")
        if response.status_code not in DOCKER_ACTION_OK_STATUS_CODES:
            raise RuntimeError(f"컨테이너 {action} 실패 · {container_name} · {response.status_code}")
