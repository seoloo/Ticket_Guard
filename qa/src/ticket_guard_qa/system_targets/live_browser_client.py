"""Live 브라우저 예매 흐름 · 브라우저 트래픽 유형(봇 C 등) · 실제 예매 화면 열기 · 버튼 클릭 · 단계별 캡처
browser 묶음(Playwright) + Chromium 필요 · 없으면 BrowserUnavailableError → 세션 오류로 기록 (Live만 · Mock은 영향 없음)"""
import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from ticket_guard_qa.domain.enums import BookingOutcome
from ticket_guard_qa.domain.models import BrowserCaptureFrame, VirtualUserSessionPlan
from ticket_guard_qa.system_targets.live_booking_client import (
    DEFAULT_SHOW_ID,
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
RESULT_POLL_INTERVAL_SEC = 0.2
BROWSER_SETUP_HINT = "browser 묶음 미설치 · pip install -e qa[browser] · playwright install chromium"

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
READ_SOLD_SEATS = "[...document.querySelectorAll('[data-seat].sold, [data-seat]:disabled')].map((seat) => seat.dataset.seat)"
IS_SELECTION_ERROR_SHOWN = "(() => { const box = document.querySelector('#selection-error'); return !!box && !box.hidden; })()"

# B3 캡처 단계 · macro_bots/browser_capture.CAPTURE_STEPS와 같은 이름
STEP_DETAIL, STEP_QUEUE, STEP_CAPTCHA, STEP_SEAT, STEP_CONFIRM = "공연 상세", "대기열", "보안문자", "좌석 선택", "예매 확정"


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


class PlaywrightBrowserPage:
    """Playwright 페이지 → BrowserPage · 클릭은 마우스 이동 궤적 없이 요소 중앙 바로 클릭"""

    def __init__(self, page: Any) -> None:
        self.page = page

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
        return await self.page.evaluate(expression)

    async def screenshot(self) -> bytes:
        return await self.page.screenshot(type="png")


@asynccontextmanager
async def open_browser_page(user_agent: str | None = None) -> AsyncIterator[BrowserPage]:
    """화면 없는 Chromium 탭 하나 · 세션 끝나면 브라우저 닫음"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise BrowserUnavailableError(BROWSER_SETUP_HINT) from None
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001 · Chromium 미설치 · 실행 권한
            raise BrowserUnavailableError(f"Chromium 실행 불가 · {type(error).__name__} · {BROWSER_SETUP_HINT}") from None
        try:
            context = await browser.new_context(viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                                                user_agent=user_agent)
            yield PlaywrightBrowserPage(await context.new_page())
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

    async def login(self, username: str, password: str) -> None:
        await self.page.goto(f"{self.base_url}/login/")
        await self.page.fill(LOGIN_USERNAME, username)
        await self.page.fill(LOGIN_PASSWORD, password)
        await self.page.click(LOGIN_SUBMIT)
        if not await self.page.wait_for(SHOW_LIST_READY, PAGE_TIMEOUT_MS):
            raise BookingFlowError("login", 0, "BROWSER_LOGIN_FAILED")

    async def browse_pages(self, page_dwell_ms: tuple[float, ...]) -> None:
        """예매 전 공연 목록 · 상세 · 마지막은 예매하기 버튼 있는 공연 상세"""
        for page_name, dwell_ms in zip(build_browse_pages(len(page_dwell_ms)), page_dwell_ms):
            path = "/" if page_name == SHOW_LIST_PAGE else f"/{SHOW_DETAIL_PAGE}/{self.show_id}/"
            await self.page.goto(f"{self.base_url}{path}")
            await asyncio.sleep(dwell_ms / 1000)
        if not page_dwell_ms:  # 조회 없는 봇도 예매하기 버튼 화면은 열어야 함
            await self.page.goto(f"{self.base_url}/{SHOW_DETAIL_PAGE}/{self.show_id}/")

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
        """시험 끝 정리 · 계정당 진행 중 예매 1건 · 실패해도 60초 뒤 시스템 만료"""
        try:
            await self.page.click(CANCEL_BOOKING)
        except Exception:  # noqa: BLE001 · 정리 실패는 결과에 영향 없음
            pass

    async def run_booking_flow(self, username: str, password: str, captcha_answer: str,
                               session_plan: VirtualUserSessionPlan, open_at_monotonic: float) -> BrowserFlowResult:
        behavior = session_plan.behavior
        self.open_at_monotonic = open_at_monotonic
        login_started_at = time.perf_counter()
        await self.login(username, password)
        step_latency_ms = {"login": (time.perf_counter() - login_started_at) * 1000}

        browse_at = open_at_monotonic - sum(session_plan.page_dwell_ms) / 1000  # 화면 조회는 오픈 전에 끝나도록
        await asyncio.sleep(max(browse_at - time.monotonic(), 0.0))
        await self.browse_pages(session_plan.page_dwell_ms)
        await asyncio.sleep(max(open_at_monotonic + session_plan.entry_delay_ms / 1000 - time.monotonic(), 0.0))

        start_started_at = time.perf_counter()
        await self.click_and_capture(STEP_DETAIL, START_BOOKING)
        step_latency_ms["start"] = (time.perf_counter() - start_started_at) * 1000
        queue_started_at = time.perf_counter()
        if await self.page.wait_for(QUEUE_READY, PAGE_TIMEOUT_MS):
            await self.capture(STEP_QUEUE, None)
        if not await self.page.wait_for(CAPTCHA_INPUT, QUEUE_TIMEOUT_MS):
            raise BookingFlowError("heartbeat", 0, "QUEUE_TIMEOUT")
        step_latency_ms["queue"] = (time.perf_counter() - queue_started_at) * 1000
        self.booking_attempt_id = str(await self.page.evaluate(READ_ATTEMPT_ID))

        captcha_started_at = time.perf_counter()
        await self.page.fill(CAPTCHA_INPUT, captcha_answer)
        await self.click_and_capture(STEP_CAPTCHA, CAPTCHA_SUBMIT)
        if not await self.page.wait_for(SEAT_READY, PAGE_TIMEOUT_MS):
            raise BookingFlowError("verify", 0, "BROWSER_CAPTCHA_FAILED")
        step_latency_ms["captcha"] = (time.perf_counter() - captcha_started_at) * 1000

        intervals_ms = session_plan.click_intervals_ms or (0.0,)
        step_latency_ms["seat_select"] = step_latency_ms["confirm"] = 0.0
        for attempt_index in range(1 + behavior.sold_out_retry_count):
            sold_seat_ids = set(await self.page.evaluate(READ_SOLD_SEATS) or ())
            seat_ids = [seat for seat in session_plan.preferred_seat_ids if seat not in sold_seat_ids][:SEATS_PER_BOOKING]
            if not seat_ids:
                break
            if attempt_index:
                await asyncio.sleep(behavior.sold_out_retry_delay_ms / 1000)
            click_started_at = time.perf_counter()
            for index, seat_id in enumerate(seat_ids):
                await asyncio.sleep(intervals_ms[index % len(intervals_ms)] / 1000)
                selector = f'[data-seat="{seat_id}"]'
                if index == 0 and not attempt_index:
                    await self.click_and_capture(STEP_SEAT, selector)
                else:
                    await self.page.click(selector)
            await asyncio.sleep(intervals_ms[-1] / 1000)
            step_latency_ms["seat_select"] += (time.perf_counter() - click_started_at) * 1000
            confirm_started_at = time.perf_counter()
            if attempt_index:
                await self.page.click(CONFIRM_BOOKING)
            else:
                await self.click_and_capture(STEP_CONFIRM, CONFIRM_BOOKING)
            is_booked = await self.wait_for_confirm_result()
            step_latency_ms["confirm"] += (time.perf_counter() - confirm_started_at) * 1000
            if is_booked:
                return BrowserFlowResult(self.booking_attempt_id, BookingOutcome.BOOKED, tuple(seat_ids), step_latency_ms,
                                         self.capture_frames)
        await self.cancel_booking()
        return BrowserFlowResult(self.booking_attempt_id, BookingOutcome.SOLD_OUT, (), step_latency_ms, self.capture_frames)
