"""Live 브라우저 예매 흐름 · 브라우저 트래픽 유형(봇 C · 봇 D 등) · 실제 예매 화면 열기 · 버튼 클릭 · 단계별 캡처
브라우저 1개 = 기기 1대 · 창(로그인 분리) 여러 개 · 봇 D = 같은 브라우저 창들이 기기 쿠키 공유
browser 묶음(Playwright) + Chromium 필요 · 없으면 BrowserUnavailableError → 세션 오류로 기록 (Live만 · Mock은 영향 없음)"""
import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from ticket_guard_qa.domain.enums import BookingOutcome
from ticket_guard_qa.domain.models import BrowserCaptureFrame, VirtualUserSessionPlan
from ticket_guard_qa.system_targets.live_booking_client import (
    DEFAULT_SHOW_ID,
    DEVICE_COOKIE_NAME,
    SEATS_PER_BOOKING,
    SHOW_DETAIL_PAGE,
    SHOW_LIST_PAGE,
    BookingFlowError,
    build_browse_pages,
)

VIEWPORT_WIDTH, VIEWPORT_HEIGHT = 1280, 800
PAGE_TIMEOUT_MS = 15_000
QUEUE_TIMEOUT_MS = 60_000  # 기본 대기 12초 + 여유
CONFIRM_RESULT_TIMEOUT_SEC = 10.0
CANCEL_RESULT_TIMEOUT_SEC = 5.0  # 취소 응답 → 다른 화면 이동
RESULT_POLL_INTERVAL_SEC = 0.2
BROWSER_SETUP_HINT = "browser 묶음 · Chromium 필요 · qa-dashboard 이미지 다시 빌드 · 내 PC = pip install -e qa[browser] · playwright install chromium"

# 예매 화면(templates/page.html) 요소 · 화면이 바뀌면 여기만
LOGIN_USERNAME = "#username"
LOGIN_PASSWORD = "#password"
LOGIN_SUBMIT = "#login-form button[type=submit]"
SHOW_LIST_READY = "[data-show-link]"
START_BOOKING = "#start-booking"
QUEUE_READY = "#queue-rank"
CAPTCHA_INPUT = "#captcha-answer"
CAPTCHA_SUBMIT = "#captcha-form button[type=submit]"
SEAT_READY = "[data-seat]"
CONFIRM_BOOKING = "#confirm-booking"
SELECTION_ERROR = "#selection-error"
CANCEL_BOOKING = "#cancel-booking"
COMPLETE_PATH = "/complete/"
READ_ATTEMPT_ID = "document.body.dataset.attempt || ''"
READ_CHOSEN_SEATS = "[...document.querySelectorAll('[data-seat][aria-pressed=\"true\"]')].map((seat) => seat.dataset.seat)"  # 화면이 선택 표시한 좌석
READ_SOLD_SEATS = "[...document.querySelectorAll('[data-seat].sold, [data-seat]:disabled')].map((seat) => seat.dataset.seat)"
IS_CAPTCHA_IMAGE_LOADED = "(() => { const image = document.querySelector('#captcha-image'); return !!image && image.complete && image.naturalWidth > 0; })()"
IS_SELECTION_ERROR_SHOWN ="(() => { const box = document.querySelector('#selection-error'); return !!box && !box.hidden; })()"
NAVIGATION_ERROR_MARKERS = ("Execution context was destroyed", "because of a navigation", "Target page, context or browser has been closed")
PAGE_TRACE_PATHS =("/api/events/", "/api/capture/")  # 화면 이벤트 · 브라우저 정보 전송 · 흔적 없음 봇은 차단

# B3 캡처 단계 · macro_bots/browser_capture.CAPTURE_STEPS와 같은 이름
STEP_DETAIL, STEP_QUEUE, STEP_CAPTCHA, STEP_SEAT, STEP_CONFIRM = "공연 상세", "대기열", "보안문자", "좌석 선택", "예매 확정"


def summarize_browser_error(error: Exception) -> str:
    """오류 첫 줄 · 주소 · 호출 기록 제외 · 화면 · 리포트 한 줄용"""
    first_line = (str(error).strip().splitlines() or [""])[0]
    return first_line.split(" at http")[0].split(": ", 1)[-1].strip()[:80]


class BrowserUnavailableError(RuntimeError):
    """브라우저 실행 환경 없음 · 설치 · 실행 실패"""


class BrowserPage(Protocol):
    """브라우저 한 탭 · Playwright 페이지 · 시험에서는 가짜 페이지"""

    @property
    def url(self) -> str: ...

    async def goto(self, url: str) -> None: ...

    async def click(self, selector: str) -> tuple[float, float] | None:
        """클릭 위치(화면 px) · 요소 없으면 None"""

    async def fill(self, selector: str, value: str) -> None: ...

    async def wait_for(self, selector: str, timeout_ms: float) -> bool: ...

    async def evaluate(self, expression: str) -> Any: ...

    async def screenshot(self) -> bytes: ...

    async def read_cookie(self, name: str) -> str | None: ...

    async def add_cookie(self, name: str, value: str, url: str) -> None: ...


class BrowserInstance(Protocol):
    """실행 중인 브라우저 1개 · 창마다 로그인 · 쿠키 분리"""

    def open_window(self, blocks_page_trace: bool) -> AbstractAsyncContextManager[BrowserPage]: ...


async def accept_dialog(dialog: Any) -> None:
    await dialog.accept()


class PlaywrightBrowserPage:
    """Playwright 페이지 → BrowserPage · 클릭은 마우스 이동 궤적 없이 요소 중앙 바로 클릭"""

    def __init__(self, page: Any) -> None:
        self.page = page
        page.on("dialog", accept_dialog)  # 예매 취소 · 화면 이동 확인 창 · 기본값(닫기)이면 취소 요청이 안 나감

    @property
    def url(self) -> str:
        return self.page.url

    async def goto(self, url: str) -> None:
        await self.page.goto(url, timeout=PAGE_TIMEOUT_MS)

    async def click(self, selector: str) -> tuple[float, float] | None:
        locator = self.page.locator(selector).first
        box = await locator.bounding_box(timeout=PAGE_TIMEOUT_MS)
        await locator.click(timeout=PAGE_TIMEOUT_MS)
        return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2) if box else None

    async def fill(self, selector: str, value: str) -> None:
        await self.page.locator(selector).first.fill(value, timeout=PAGE_TIMEOUT_MS)

    async def wait_for(self, selector: str, timeout_ms: float) -> bool:
        try:
            await self.page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        except Exception:  # noqa: BLE001 · 시간 초과 = 화면 안 바뀜
            return False
        return True

    async def evaluate(self, expression: str) -> Any:
        """화면 이동 중이면 None · 확정 클릭 직후 완료 화면으로 넘어가는 순간 · 호출한 쪽이 다시 읽음"""
        try:
            return await self.page.evaluate(expression)
        except Exception as error:  # noqa: BLE001 · Playwright 오류 종류는 Error 하나
            if any(marker in str(error) for marker in NAVIGATION_ERROR_MARKERS):
                return None
            raise

    async def screenshot(self) -> bytes:
        return await self.page.screenshot(type="png")

    async def read_cookie(self, name: str) -> str | None:
        """httponly 쿠키 포함 · 기기 쿠키는 화면 스크립트로 못 읽음"""
        return next((cookie["value"] for cookie in await self.page.context.cookies() if cookie["name"] == name), None)

    async def add_cookie(self, name: str, value: str, url: str) -> None:
        await self.page.context.add_cookies([{"name": name, "value": value, "url": url}])


def is_page_trace_url(url: str) -> bool:
    return urlparse(url).path.startswith(PAGE_TRACE_PATHS)


class PlaywrightBrowser:
    """Chromium 1개 · 창 = 쿠키 분리 창(시크릿 창과 같음) · 탭은 로그인 쿠키를 같이 써서 계정 여러 개 불가 · 브라우저 정보는 창끼리 같음"""

    def __init__(self, browser: Any, user_agent: str | None) -> None:
        self.browser = browser
        self.user_agent = user_agent

    @asynccontextmanager
    async def open_window(self, blocks_page_trace: bool) -> AsyncIterator[BrowserPage]:
        context = await self.browser.new_context(viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                                                 user_agent=self.user_agent)
        try:
            if blocks_page_trace:  # 흔적 없는 매크로 · 화면 스크립트의 이벤트 전송 차단
                await context.route(is_page_trace_url, lambda route: route.abort())
            yield PlaywrightBrowserPage(await context.new_page())
        finally:
            await context.close()


CHROMIUM_LAUNCH_ARGS = ["--disable-dev-shm-usage"]  # 컨테이너 공유 메모리(/dev/shm) 작음 · 탭 비정상 종료 방지
TRUSTED_ORIGIN_ARG = "--unsafely-treat-insecure-origin-as-secure="  # http://web:8000 = 보안 컨텍스트 아님 → 예매 화면 crypto.randomUUID 없음


def build_trusted_origin(base_url: str) -> str:
    """시험 대상 주소 · 운영 HTTPS처럼 보안 컨텍스트로 · localhost · https는 필요 없음"""
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname in ("localhost", "127.0.0.1"):
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


@asynccontextmanager
async def open_browser(user_agent: str | None = None, executable_path: str = "",
                       trusted_origin: str = "") -> AsyncIterator[BrowserInstance]:
    """화면 없는 Chromium 1개 · 다 쓰면 닫음 · executable_path = 설치된 Chromium(비면 Playwright 기본)"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise BrowserUnavailableError(BROWSER_SETUP_HINT) from None
    launch_args = [*CHROMIUM_LAUNCH_ARGS, *([f"{TRUSTED_ORIGIN_ARG}{trusted_origin}"] if trusted_origin else [])]
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True, executable_path=executable_path or None,
                                                       args=launch_args)
        except Exception as error:  # noqa: BLE001 · Chromium 미설치 · 실행 권한
            raise BrowserUnavailableError(f"Chromium 실행 불가 · {type(error).__name__} · {BROWSER_SETUP_HINT}") from None
        try:
            yield PlaywrightBrowser(browser, user_agent)
        finally:
            await browser.close()


@dataclass
class BrowserFlowResult:
    booking_attempt_id: str
    booking_outcome: BookingOutcome
    booked_seat_ids: tuple[str, ...] = ()
    step_latency_ms: dict[str, float] = field(default_factory=dict)
    capture_frames: list[BrowserCaptureFrame] = field(default_factory=list)


class LiveBrowserBookingClient:
    """사람처럼 화면을 거쳐 예매 · 행동 값(화면 조회 · 시작 시점 · 클릭 간격 · 매진 대응)대로 · 단계마다 캡처"""

    def __init__(self, page: BrowserPage, base_url: str, show_id: str = DEFAULT_SHOW_ID) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.show_id = show_id
        self.open_at_monotonic = 0.0
        self.booking_attempt_id = ""
        self.current_step = "login"  # 오류 기록용 · 지금 진행 중인 단계
        self.capture_frames: list[BrowserCaptureFrame] = []

    async def capture(self, step: str, click_point: tuple[float, float] | None) -> None:
        elapsed_ms = (time.monotonic() - self.open_at_monotonic) * 1000
        ratio = (click_point[0] / VIEWPORT_WIDTH, click_point[1] / VIEWPORT_HEIGHT) if click_point else (None, None)
        self.capture_frames.append(BrowserCaptureFrame(step, round(elapsed_ms, 1), *ratio, await self.page.screenshot()))

    async def click_and_capture(self, step: str, selector: str) -> None:
        """클릭 직전 화면 + 클릭 위치 · B3 캡처"""
        screenshot = await self.page.screenshot()
        point = await self.page.click(selector)
        elapsed_ms = (time.monotonic() - self.open_at_monotonic) * 1000
        ratio = (point[0] / VIEWPORT_WIDTH, point[1] / VIEWPORT_HEIGHT) if point else (None, None)
        self.capture_frames.append(BrowserCaptureFrame(step, round(elapsed_ms, 1), *ratio, screenshot))

    async def join_device(self, device_cookie: str | None) -> str | None:
        """같은 기기 창 · 먼저 연 창의 기기 쿠키를 그대로 사용 · 첫 창이면 새로 받은 쿠키 반환"""
        if device_cookie:
            await self.page.add_cookie(DEVICE_COOKIE_NAME, device_cookie, self.base_url)
            return device_cookie
        await self.page.goto(f"{self.base_url}/login/")
        return await self.page.read_cookie(DEVICE_COOKIE_NAME)

    async def login(self, username: str, password: str) -> None:
        await self.page.goto(f"{self.base_url}/login/")
        await self.page.fill(LOGIN_USERNAME, username)
        await self.page.fill(LOGIN_PASSWORD, password)
        await self.page.click(LOGIN_SUBMIT)
        if not await self.page.wait_for(SHOW_LIST_READY, PAGE_TIMEOUT_MS):
            if f"{LOGIN_USERNAME.removeprefix('#')}=" in self.page.url:  # 화면 스크립트 미동작 → 폼이 주소로 제출됨
                raise BookingFlowError("login", 0, "BROWSER_SCRIPT_NOT_RUNNING")
            raise BookingFlowError("login", 0, "BROWSER_LOGIN_FAILED")

    async def browse_pages(self, page_dwell_ms: tuple[float, ...]) -> None:
        """예매 전 공연 목록 · 상세 · 마지막은 예매하기 버튼 있는 공연 상세"""
        for page_name, dwell_ms in zip(build_browse_pages(len(page_dwell_ms)), page_dwell_ms):
            path = "/" if page_name == SHOW_LIST_PAGE else f"/{SHOW_DETAIL_PAGE}/{self.show_id}/"
            await self.page.goto(f"{self.base_url}{path}")
            await asyncio.sleep(dwell_ms / 1000)
        if not page_dwell_ms:  # 조회 없는 봇도 예매하기 버튼 화면은 열어야 함
            await self.page.goto(f"{self.base_url}/{SHOW_DETAIL_PAGE}/{self.show_id}/")

    async def wait_for_captcha_image(self) -> None:
        """보안문자 정답은 이미지 요청 때 생성 · 입력칸이 먼저 보여도 이미지가 뜬 뒤 입력"""
        deadline = time.monotonic() + PAGE_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            if await self.page.evaluate(IS_CAPTCHA_IMAGE_LOADED):
                return
            await asyncio.sleep(RESULT_POLL_INTERVAL_SEC)
        raise BookingFlowError("captcha_image", 0, "BROWSER_CAPTCHA_IMAGE_NOT_LOADED")

    async def wait_for_confirm_result(self) -> bool:
        """True = 예매 완료 화면 · False = 먼저 팔림 안내"""
        deadline = time.monotonic() + CONFIRM_RESULT_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if COMPLETE_PATH in self.page.url:
                return True
            if await self.page.evaluate(IS_SELECTION_ERROR_SHOWN):
                return False
            await asyncio.sleep(RESULT_POLL_INTERVAL_SEC)
        raise BookingFlowError("confirm", 0, "BROWSER_CONFIRM_TIMEOUT")

    async def cancel_booking(self) -> None:
        """시험 끝 정리 · 계정당 진행 중 예매 1건 · 취소 응답 뒤 화면 이동까지 대기(창을 바로 닫으면 요청 중단)
        실패해도 60초 뒤 시스템 만료"""
        try:
            cancel_from_url = self.page.url
            await self.page.click(CANCEL_BOOKING)
            deadline = time.monotonic() + CANCEL_RESULT_TIMEOUT_SEC
            while self.page.url == cancel_from_url and time.monotonic() < deadline:
                await asyncio.sleep(RESULT_POLL_INTERVAL_SEC)
        except Exception:  # noqa: BLE001 · 정리 실패는 결과에 영향 없음
            pass

    async def run_booking_flow(self, username: str, password: str, captcha_answer: str,
                               session_plan: VirtualUserSessionPlan, open_at_monotonic: float) -> BrowserFlowResult:
        behavior = session_plan.behavior
        self.open_at_monotonic = open_at_monotonic
        login_started_at = time.perf_counter()
        self.current_step = "login"
        await self.login(username, password)
        step_latency_ms = {"login": (time.perf_counter() - login_started_at) * 1000}

        browse_at = open_at_monotonic - sum(session_plan.page_dwell_ms) / 1000  # 화면 조회는 오픈 전에 끝나도록
        await asyncio.sleep(max(browse_at - time.monotonic(), 0.0))
        self.current_step = "browse"
        await self.browse_pages(session_plan.page_dwell_ms)
        await asyncio.sleep(max(open_at_monotonic + session_plan.entry_delay_ms / 1000 - time.monotonic(), 0.0))

        self.current_step = "start"
        start_started_at = time.perf_counter()
        await self.click_and_capture(STEP_DETAIL, START_BOOKING)
        step_latency_ms["start"] = (time.perf_counter() - start_started_at) * 1000
        self.current_step = "queue"
        queue_started_at = time.perf_counter()
        if await self.page.wait_for(QUEUE_READY, PAGE_TIMEOUT_MS):
            await self.capture(STEP_QUEUE, None)
        if not await self.page.wait_for(CAPTCHA_INPUT, QUEUE_TIMEOUT_MS):
            raise BookingFlowError("heartbeat", 0, "QUEUE_TIMEOUT")
        step_latency_ms["queue"] = (time.perf_counter() - queue_started_at) * 1000
        self.booking_attempt_id = str(await self.page.evaluate(READ_ATTEMPT_ID) or "")

        self.current_step = "captcha"
        captcha_started_at = time.perf_counter()
        await self.wait_for_captcha_image()
        await self.page.fill(CAPTCHA_INPUT, captcha_answer)
        await self.click_and_capture(STEP_CAPTCHA, CAPTCHA_SUBMIT)
        if not await self.page.wait_for(SEAT_READY, PAGE_TIMEOUT_MS):
            raise BookingFlowError("verify", 0, "BROWSER_CAPTCHA_FAILED")
        step_latency_ms["captcha"] = (time.perf_counter() - captcha_started_at) * 1000

        intervals_ms = session_plan.click_intervals_ms or (0.0,)
        step_latency_ms["seat_select"] = step_latency_ms["confirm"] = 0.0
        for attempt_index in range(1 + behavior.sold_out_retry_count):
            self.current_step = "seat"
            sold_seat_ids = set(await self.page.evaluate(READ_SOLD_SEATS) or ())
            # 먼저 팔림 안내 뒤 화면은 남은 선택 좌석을 유지 · 다시 누르면 선택 해제 → 새 좌석만 클릭
            kept_seat_ids = [seat for seat in (await self.page.evaluate(READ_CHOSEN_SEATS) or ()) if seat not in sold_seat_ids]
            new_seat_ids = [seat for seat in session_plan.preferred_seat_ids
                            if seat not in sold_seat_ids and seat not in kept_seat_ids][:max(SEATS_PER_BOOKING - len(kept_seat_ids), 0)]
            if not new_seat_ids and not kept_seat_ids:
                break
            if attempt_index:
                await asyncio.sleep(behavior.sold_out_retry_delay_ms / 1000)
            click_started_at = time.perf_counter()
            for index, seat_id in enumerate(new_seat_ids):
                await asyncio.sleep(intervals_ms[index % len(intervals_ms)] / 1000)
                selector = f'[data-seat="{seat_id}"]'
                if index == 0 and not attempt_index:
                    await self.click_and_capture(STEP_SEAT, selector)
                else:
                    await self.page.click(selector)
            await asyncio.sleep(intervals_ms[-1] / 1000)
            step_latency_ms["seat_select"] += (time.perf_counter() - click_started_at) * 1000
            chosen_seat_ids = tuple(await self.page.evaluate(READ_CHOSEN_SEATS) or (*kept_seat_ids, *new_seat_ids))  # 서버로 보내는 좌석
            self.current_step = "confirm"
            confirm_started_at = time.perf_counter()
            if attempt_index:
                await self.page.click(CONFIRM_BOOKING)
            else:
                await self.click_and_capture(STEP_CONFIRM, CONFIRM_BOOKING)
            is_booked = await self.wait_for_confirm_result()
            step_latency_ms["confirm"] += (time.perf_counter() - confirm_started_at) * 1000
            if is_booked:
                return BrowserFlowResult(self.booking_attempt_id, BookingOutcome.BOOKED, chosen_seat_ids, step_latency_ms,
                                         self.capture_frames)
        await self.cancel_booking()
        return BrowserFlowResult(self.booking_attempt_id, BookingOutcome.SOLD_OUT, (), step_latency_ms, self.capture_frames)
