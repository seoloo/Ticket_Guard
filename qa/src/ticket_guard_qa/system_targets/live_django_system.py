"""지금의 Django 시스템에 HTTP로 접속 · 시스템 코드 import 금지"""
import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from dataclasses import dataclass
from typing import Any

import httpx

from ticket_guard_qa.domain.enums import BookingOutcome
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
    choose_user_agent,
    has_browser_trace,
)
from ticket_guard_qa.system_targets.live_browser_client import (
    BrowserInstance,
    BrowserUnavailableError,
    LiveBrowserBookingClient,
    build_trusted_origin,
    summarize_browser_error,
    open_browser,
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
DEFAULT_MAX_CONCURRENT_BROWSERS = 8  # 설정 max_concurrent_browsers · 브라우저 1개 = 메모리 약 300MB · 나머지 브라우저 VU는 대기
WINDOWS_PER_BROWSER_LIMIT = 3  # 창 상한 = 브라우저 수 × 3 · 봇 D 기기 창 · 실측 브라우저 4 · 창 16 = 약 2.3GB
HEALTH_CHECK_TIMEOUT_SEC = 1.5  # 화면 헤더용 · 오래 기다리지 않음
BOOKING_ID_PATH_PREFIX = "/complete/"  # 확정 200 응답 redirect · /complete/TG-…/


def read_booking_id(body: dict[str, Any]) -> str | None:
    redirect = body.get("redirect") or ""
    if not redirect.startswith(BOOKING_ID_PATH_PREFIX):
        return None
    return redirect.removeprefix(BOOKING_ID_PATH_PREFIX).strip("/") or None


def shares_device(session_plan: VirtualUserSessionPlan) -> bool:
    """봇 D 등 · 기기 1대당 예매 창 2개 이상"""
    return session_plan.behavior.sessions_per_device > 1 and bool(session_plan.device_key)


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


@dataclass
class SharedDeviceBrowser:
    """봇 D 기기 1대 · 브라우저 1개를 창들이 함께 사용 · 마지막 창이 닫을 때 브라우저 종료"""
    browser: BrowserInstance
    closer: AsyncExitStack
    window_count: int = 0


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
                 transport: httpx.AsyncBaseTransport | None = None,
                 queue_admission_limit: int = 0,
                 browser_executable_path: str = "",
                 max_concurrent_browsers: int = DEFAULT_MAX_CONCURRENT_BROWSERS) -> None:
        self.max_concurrent_browsers = max(max_concurrent_browsers, 1)
        self.queue_admission_limit = queue_admission_limit  # 시스템 동시 입장 상한 · 0 = 모름
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.test_accounts = test_accounts or VirtualUserAccountPool(0, "", "")
        self.admin_account = admin_account or SystemAdminAccount()
        self.transport = transport
        self.contract_runner: asyncio.Runner | None = None  # 계약 시험 · 개발 계정 한 개 · 요청 사이 로그인 유지
        self.contract_client: LiveBookingClient | None = None
        self.device_cookie_by_key: dict[str, str] = {}  # 봇 D · 같은 기기 예매 창 쿠키 공유 · 실행마다 새로
        self.device_lock_by_key: dict[str, asyncio.Lock] = {}
        self.device_browser_by_key: dict[str, SharedDeviceBrowser] = {}
        self.device_loop: asyncio.AbstractEventLoop | None = None
        self.browser_loop: asyncio.AbstractEventLoop | None = None
        self.browser_slots: asyncio.Semaphore | None = None
        self.window_slots: asyncio.Semaphore | None = None
        self.browser_opener = partial(open_browser, executable_path=browser_executable_path,
                                      trusted_origin=build_trusted_origin(self.base_url))  # 시험에서 가짜 브라우저로 교체
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
        """새 계정 먼저 · 다 쓰면 정리 끝난 계정 · 계정당 진행 중 예매 1건(DUPLICATE_PAGE) · 나눠서 진입 회차 사이 재사용 최소화"""
        if self.issued_account_count < self.test_accounts.count:
            self.issued_account_count += 1
            return self.issued_account_count
        if self.free_account_numbers:
            return self.free_account_numbers.pop(0)
        raise AccountPoolExhaustedError(
            f"시험 계정 부족 · {self.test_accounts.count}개 · 저장소 .env QA_TEST_ACCOUNT_COUNT 확인"
        )

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
        self.issued_account_count = 0  # 진행 중 예매 전부 정리됨 · 계정 처음부터
        self.free_account_numbers.clear()
        return True

    async def _reset_as_admin(self) -> None:
        admin_client = LiveBookingClient(self.base_url, self.transport)
        try:
            await admin_client.login(self.admin_account.username, self.admin_account.password)
            await admin_client.reset_test_data()  # 404 = 시스템 QA_RESET_ENABLED 꺼짐
        finally:
            await admin_client.close()

    def find_device_lock(self, device_key: str) -> asyncio.Lock:
        """실행(이벤트 루프)이 바뀌면 기기 묶음 초기화 · 다른 Run과 기기 쿠키 공유 금지"""
        running_loop = asyncio.get_running_loop()
        if self.device_loop is not running_loop:
            self.device_loop = running_loop
            self.device_cookie_by_key.clear()
            self.device_lock_by_key.clear()
            self.device_browser_by_key.clear()
        return self.device_lock_by_key.setdefault(device_key, asyncio.Lock())

    async def attach_device(self, client: LiveBookingClient | LiveBrowserBookingClient,
                            session_plan: VirtualUserSessionPlan) -> None:
        """기기 1대당 예매 창 2개 이상일 때만 · 첫 창이 받은 기기 쿠키를 나머지 창이 그대로 사용"""
        if not shares_device(session_plan):
            return
        async with self.find_device_lock(session_plan.device_key):
            device_cookie = await client.join_device(self.device_cookie_by_key.get(session_plan.device_key))
            if device_cookie:
                self.device_cookie_by_key[session_plan.device_key] = device_cookie

    def find_browser_slots(self) -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
        """동시에 띄우는 브라우저 · 창 수 제한 · 실행(이벤트 루프)마다 새로"""
        running_loop = asyncio.get_running_loop()
        if self.browser_loop is not running_loop:
            self.browser_loop = running_loop
            self.browser_slots = asyncio.Semaphore(self.max_concurrent_browsers)
            self.window_slots = asyncio.Semaphore(self.max_concurrent_browsers * WINDOWS_PER_BROWSER_LIMIT)
        return self.browser_slots, self.window_slots

    @asynccontextmanager
    async def use_browser(self, session_plan: VirtualUserSessionPlan) -> AsyncIterator[BrowserInstance]:
        """봇 C 등 = 세션마다 브라우저 1개 · 봇 D = 기기 1대당 브라우저 1개를 그 기기 창들이 함께 사용"""
        browser_slots, _ = self.find_browser_slots()
        user_agent = choose_user_agent(session_plan.behavior)
        if not shares_device(session_plan):
            async with browser_slots, self.browser_opener(user_agent) as browser:
                yield browser
            return
        device_key = session_plan.device_key
        async with self.find_device_lock(device_key):
            shared = self.device_browser_by_key.get(device_key)
            if shared is None:
                closer = AsyncExitStack()
                try:
                    await closer.enter_async_context(browser_slots)
                    browser = await closer.enter_async_context(self.browser_opener(user_agent))
                except BaseException:
                    await closer.aclose()
                    raise
                shared = self.device_browser_by_key[device_key] = SharedDeviceBrowser(browser, closer)
            shared.window_count += 1
        try:
            yield shared.browser
        finally:
            async with self.find_device_lock(device_key):
                shared.window_count -= 1
                if shared.window_count == 0:
                    self.device_browser_by_key.pop(device_key, None)
                    await shared.closer.aclose()

    async def run_browser_session(
        self, session_plan: VirtualUserSessionPlan, open_at_monotonic: float
    ) -> VirtualUserSessionResult:
        """브라우저 트래픽 유형 · 실제 화면으로 예매 · 실행 환경 없으면 세션 오류(browser)로 기록
        계정 반환 = 예매 완료 또는 예매 시도 전 · 매진 · 오류는 취소 미확인 → 반환 안 함(DUPLICATE_PAGE 방지 · 60초 뒤 시스템 만료)"""
        account_number = self.acquire_account_number()
        username = build_test_account_username(account_number)
        attempt_id = ""
        is_booked = False
        current_step = "window"  # 창 열기 전 · 브라우저 실행 중 오류
        blocks_page_trace = not has_browser_trace(session_plan.behavior)
        try:
            _, window_slots = self.find_browser_slots()
            async with self.use_browser(session_plan) as browser, window_slots, \
                    browser.open_window(blocks_page_trace) as page:
                client = LiveBrowserBookingClient(page, self.base_url)
                current_step = "device"  # 같은 기기 쿠키 받기
                await self.attach_device(client, session_plan)
                try:
                    flow_result = await client.run_booking_flow(
                        username, self.test_accounts.password, self.test_accounts.captcha_answer, session_plan, open_at_monotonic
                    )
                    is_booked = flow_result.booking_outcome is BookingOutcome.BOOKED
                finally:
                    current_step = client.current_step  # 오류 기록 · 멈춘 단계
                    attempt_id = client.booking_attempt_id
        except BrowserUnavailableError as error:
            return VirtualUserSessionResult(SessionKey(f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"browser · 실행 환경 없음 · {error}", device_key=session_plan.device_key)
        except BookingFlowError as error:
            return VirtualUserSessionResult(SessionKey(attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"browser {error.step} · {error.error_code or error.status_code}",
                                            device_key=session_plan.device_key)
        except Exception as error:  # noqa: BLE001 · 브라우저 오류 하나가 Run 전체를 멈추지 않게
            return VirtualUserSessionResult(SessionKey(attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"browser {current_step} · {type(error).__name__} · {summarize_browser_error(error)}",
                                            device_key=session_plan.device_key)
        finally:
            if is_booked or not attempt_id:
                self.free_account_numbers.append(account_number)
        return VirtualUserSessionResult(
            SessionKey(flow_result.booking_attempt_id), sum(flow_result.step_latency_ms.values()), is_error=False,
            step_latency_ms=flow_result.step_latency_ms, booking_outcome=flow_result.booking_outcome,
            booked_seat_ids=flow_result.booked_seat_ids, device_key=session_plan.device_key,
            capture_frames=tuple(flow_result.capture_frames),
        )

    async def run_virtual_user_session(
        self, session_plan: VirtualUserSessionPlan, open_at_monotonic: float
    ) -> VirtualUserSessionResult:
        """시험 계정 하나로 예매 확정까지 → 확정 못 했으면 예매 취소로 계정 반환 · 브라우저 유형은 화면으로"""
        if session_plan.uses_browser:
            return await self.run_browser_session(session_plan, open_at_monotonic)
        account_number = self.acquire_account_number()
        username = build_test_account_username(account_number)
        client = LiveBookingClient(self.base_url, self.transport, choose_user_agent(session_plan.behavior))
        try:
            await self.attach_device(client, session_plan)
            flow_result = await client.run_booking_flow(
                username, self.test_accounts.password, self.test_accounts.captcha_answer, session_plan, open_at_monotonic
            )
        except BookingFlowError as error:
            return VirtualUserSessionResult(SessionKey(client.booking_attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"{error.step} · {error.error_code or error.status_code}",
                                            sent_event_ids=tuple(client.sent_event_ids), device_key=session_plan.device_key)
        except httpx.HTTPError as error:
            return VirtualUserSessionResult(SessionKey(client.booking_attempt_id or f"failed-{username}"), 0.0, is_error=True,
                                            failed_step=f"connection · {type(error).__name__}",
                                            sent_event_ids=tuple(client.sent_event_ids), device_key=session_plan.device_key)
        finally:
            await self.release_client(client, account_number)
        return VirtualUserSessionResult(
            SessionKey(flow_result.booking_attempt_id), flow_result.total_latency_ms, is_error=False,
            step_latency_ms=flow_result.step_latency_ms, booking_outcome=flow_result.booking_outcome,
            booked_seat_ids=flow_result.booked_seat_ids, sent_event_ids=tuple(client.sent_event_ids),
            device_key=session_plan.device_key,
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

    def admission_limit(self) -> int | None:
        return self.queue_admission_limit or None

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


def build_missing_container_message(service_name: str) -> str:
    return f"{service_name} 컨테이너 이름 미설정 · TICKET_GUARD_QA_PIPELINE_CONTAINER_NAME · Docker 소켓 연결"


class LiveDockerProcessControl:
    """Docker Engine API · 소켓으로 컨테이너 중지 · 시작 · 이름 미설정 서비스 = 건너뜀"""

    def __init__(self, container_name_by_service: dict[str, str], socket_path: str,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.container_name_by_service = {service: name for service, name in container_name_by_service.items() if name}
        self.socket_path = socket_path
        self.transport = transport

    def can_control(self, service_name: str) -> bool:
        return service_name in self.container_name_by_service

    def stop_service(self, service_name: str) -> None:
        self.send_container_action(service_name, "stop")

    def start_service(self, service_name: str) -> None:
        self.send_container_action(service_name, "start")

    def send_container_action(self, service_name: str, action: str) -> None:
        container_name = self.container_name_by_service.get(service_name)
        if not container_name:
            raise NotImplementedError(build_missing_container_message(service_name))
        transport = self.transport or httpx.HTTPTransport(uds=self.socket_path)
        with httpx.Client(base_url=DOCKER_API_BASE_URL, transport=transport, timeout=DOCKER_ACTION_TIMEOUT_SEC) as client:
            response = client.post(f"/containers/{container_name}/{action}")
        if response.status_code not in DOCKER_ACTION_OK_STATUS_CODES:
            raise RuntimeError(f"컨테이너 {action} 실패 · {container_name} · {response.status_code}")
