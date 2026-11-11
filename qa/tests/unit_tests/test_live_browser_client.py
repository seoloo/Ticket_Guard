"""Live 브라우저 예매 흐름 · 브라우저 없이 가짜 페이지로 확인 · 단계 순서 · 캡처 · 매진 재시도 · 실행 환경 없음 · 봇 D 기기 공유"""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx

from ticket_guard_qa.domain.enums import ActorType, BookingOutcome
from ticket_guard_qa.domain.models import PlannedUser, VirtualUserSessionPlan
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE, BotProfileRegistry
from ticket_guard_qa.macro_bots.browser_capture import CAPTURE_FOLDER_NAME, CAPTURE_INDEX_FILE_NAME, load_capture_frames
from ticket_guard_qa.system_targets import live_browser_client as browser
from ticket_guard_qa.system_targets.live_browser_client import BrowserUnavailableError, LiveBrowserBookingClient
from ticket_guard_qa.system_targets.live_booking_client import DEVICE_COOKIE_NAME
from ticket_guard_qa.system_targets.live_django_system import LiveDjangoBookingApi, SystemAdminAccount, VirtualUserAccountPool
from ticket_guard_qa.traffic_generators.virtual_user_traffic import (
    assign_devices,
    build_planned_user_session_plans,
    save_browser_captures,
    send_virtual_user_traffic,
)

BASE_URL = "http://web:8000"
BOT_C_BEHAVIOR = replace(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_C], sold_out_retry_delay_ms=0)
BOT_D_BEHAVIOR = replace(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_D], sold_out_retry_delay_ms=0, sessions_per_device=3)
CLICK_POINT = (640.0, 400.0)


class FakeBrowserPage:
    """예매 화면 흉내 · 클릭 순서 기록 · 먼저 팔린 좌석은 확정 때 드러남"""

    def __init__(self, hidden_sold_seat_ids: set[str] | None = None, is_queue_stuck: bool = False,
                 shown_sold_seat_ids: set[str] | None = None) -> None:
        self.url = ""
        self.clicks: list[str] = []
        self.filled: dict[str, str] = {}
        self.visited: list[str] = []
        self.hidden_sold_seat_ids = set(hidden_sold_seat_ids or ())
        self.shown_sold_seat_ids: set[str] = set(shown_sold_seat_ids or ())
        self.chosen_seat_ids: list[str] = []
        self.is_selection_error_shown = False
        self.is_queue_stuck = is_queue_stuck
        self.cookies: dict[str, str] = {}
        self.issued_device_cookie = ""

    async def goto(self, url: str) -> None:
        self.url = url
        self.visited.append(url.removeprefix(BASE_URL))

    async def click(self, selector: str):
        self.clicks.append(selector)
        if selector == browser.LOGIN_SUBMIT:
            self.url = f"{BASE_URL}/"
        elif selector == browser.START_BOOKING:
            self.url = f"{BASE_URL}/queue/attempt-77/"
        elif selector == browser.CAPTCHA_SUBMIT:
            self.url = f"{BASE_URL}/select/attempt-77/"
        elif selector.startswith("[data-seat="):  # 예매 화면처럼 · 다시 누르면 선택 해제
            seat_id = selector.split('"')[1]
            if seat_id in self.chosen_seat_ids:
                self.chosen_seat_ids.remove(seat_id)
            else:
                self.chosen_seat_ids.append(seat_id)
            self.is_selection_error_shown = False
        elif selector == browser.CANCEL_BOOKING:  # 확인 창 수락 → 취소 응답 → 공연 상세로 이동
            self.url = f"{BASE_URL}/show/1/"
        elif selector == browser.CONFIRM_BOOKING:
            sold = self.hidden_sold_seat_ids.intersection(self.chosen_seat_ids)
            if sold:  # 예매 화면처럼 · 팔린 좌석만 선택 해제 · 나머지 선택 유지
                self.shown_sold_seat_ids |= sold
                self.is_selection_error_shown = True
                self.chosen_seat_ids = [seat for seat in self.chosen_seat_ids if seat not in sold]
            else:
                self.booked_seat_ids = list(self.chosen_seat_ids)
                self.url = f"{BASE_URL}/complete/TG-1/"
        return CLICK_POINT

    async def fill(self, selector: str, value: str) -> None:
        self.filled[selector] = value

    async def wait_for(self, selector: str, timeout_ms: float) -> bool:
        return not (self.is_queue_stuck and selector == browser.CAPTCHA_INPUT)

    async def evaluate(self, expression: str):
        if expression == browser.READ_ATTEMPT_ID:
            return "attempt-77"
        if expression == browser.READ_CHOSEN_SEATS:
            return list(self.chosen_seat_ids)
        if expression == browser.READ_SOLD_SEATS:
            return sorted(self.shown_sold_seat_ids)
        if expression == browser.IS_SELECTION_ERROR_SHOWN:
            return self.is_selection_error_shown
        if expression == browser.IS_CAPTCHA_IMAGE_LOADED:
            return True
        raise AssertionError(expression)

    async def screenshot(self) -> bytes:
        return b"\x89PNG-fake"

    async def read_cookie(self, name: str) -> str | None:
        if name == DEVICE_COOKIE_NAME and self.issued_device_cookie:  # 첫 화면 응답이 기기 쿠키를 줌
            self.cookies.setdefault(name, self.issued_device_cookie)
        return self.cookies.get(name)

    async def add_cookie(self, name: str, value: str, url: str) -> None:
        self.cookies[name] = value


class FakeBrowser:
    """브라우저 1개 · 창마다 새 가짜 페이지 · 창마다 처음 받는 기기 쿠키는 브라우저 번호 · 창 번호로"""

    def __init__(self, browser_number: int, user_agent: str | None, page_factory) -> None:
        self.browser_number = browser_number
        self.user_agent = user_agent
        self.page_factory = page_factory
        self.pages: list[FakeBrowserPage] = []
        self.blocked_trace_flags: list[bool] = []
        self.is_closed = False

    @asynccontextmanager
    async def open_window(self, blocks_page_trace: bool):
        page = self.page_factory()
        page.issued_device_cookie = f"device-cookie-{self.browser_number}-{len(self.pages) + 1}"
        self.pages.append(page)
        self.blocked_trace_flags.append(blocks_page_trace)
        yield page


def build_plan(seat_ids=("C3", "C4", "C5", "C6"), behavior=BOT_C_BEHAVIOR) -> VirtualUserSessionPlan:
    return VirtualUserSessionPlan(behavior, 0.0, (0.0, 0.0, 0.0), seat_ids, page_dwell_ms=(0.0,), uses_browser=True)


def run_flow(page: FakeBrowserPage, plan: VirtualUserSessionPlan):
    client = LiveBrowserBookingClient(page, BASE_URL)
    return asyncio.run(client.run_booking_flow("qa-user-0001", "pw", "QA123", plan, time.monotonic()))


def test_browser_flow_clicks_screens_in_booking_order_and_captures_each_step():
    page = FakeBrowserPage()
    result = run_flow(page, build_plan())

    assert (result.booking_outcome, result.booked_seat_ids, result.booking_attempt_id) == (BookingOutcome.BOOKED, ("C3", "C4"), "attempt-77")
    assert page.visited == ["/login/", "/detail/blue-hour/"]  # 화면 조회 1회 = 공연 상세
    assert page.filled == {browser.LOGIN_USERNAME: "qa-user-0001", browser.LOGIN_PASSWORD: "pw", browser.CAPTCHA_INPUT: "QA123"}
    assert page.clicks == [browser.LOGIN_SUBMIT, browser.START_BOOKING, browser.CAPTCHA_SUBMIT,
                           '[data-seat="C3"]', '[data-seat="C4"]', browser.CONFIRM_BOOKING]
    assert [frame.step for frame in result.capture_frames] == ["공연 상세", "대기열", "보안문자", "좌석 선택", "예매 확정"]
    assert result.capture_frames[0].click_ratio_x == 0.5 and result.capture_frames[1].click_ratio_x is None  # 대기열 = 클릭 없음
    assert all(frame.image_png for frame in result.capture_frames)


def test_browser_flow_retries_other_seats_after_sold_notice():
    page = FakeBrowserPage(hidden_sold_seat_ids={"C3"})
    result = run_flow(page, build_plan())

    assert (result.booking_outcome, result.booked_seat_ids) == (BookingOutcome.BOOKED, ("C4", "C5"))
    assert page.clicks.count(browser.CONFIRM_BOOKING) == 2
    assert page.clicks.count('[data-seat="C4"]') == 1  # 남은 선택 좌석은 다시 누르지 않음 · 누르면 선택 해제
    assert page.booked_seat_ids == list(result.booked_seat_ids)  # QA 기록 = 서버로 보낸 좌석


def test_browser_flow_gives_up_when_retry_count_is_zero():
    page = FakeBrowserPage(hidden_sold_seat_ids={"C3"})
    result = run_flow(page, build_plan(behavior=replace(BOT_C_BEHAVIOR, sold_out_retry_count=0)))

    assert result.booking_outcome is BookingOutcome.SOLD_OUT
    assert page.clicks[-1] == browser.CANCEL_BOOKING  # 계정 정리
    assert page.url == f"{BASE_URL}/show/1/"  # 취소 응답 뒤 화면 이동까지 대기


def test_browser_flow_skips_confirm_when_wanted_seats_are_already_sold():
    plan = build_plan()
    page = FakeBrowserPage(shown_sold_seat_ids=set(plan.preferred_seat_ids))
    result = run_flow(page, plan)

    assert result.booking_outcome is BookingOutcome.SOLD_OUT
    assert browser.CONFIRM_BOOKING not in page.clicks
    assert result.step_latency_ms["confirm"] == 0.0  # 이벤트 전달 검증 · 확정 이벤트 요구 안 함
    assert page.clicks[-1] == browser.CANCEL_BOOKING


class FakePlaywrightDialog:
    def __init__(self) -> None:
        self.is_accepted = False

    async def accept(self) -> None:
        self.is_accepted = True


def test_playwright_page_accepts_confirm_dialogs():
    handlers = {}
    page = type("FakePlaywrightPage", (), {"on": lambda self, event, handler: handlers.setdefault(event, handler)})()
    browser.PlaywrightBrowserPage(page)
    dialog = FakePlaywrightDialog()
    asyncio.run(handlers["dialog"](dialog))
    assert dialog.is_accepted  # 예매 취소 확인 창 · 닫히면 취소 요청이 안 나감


def build_live_api(page_factory, account_count: int = 2) -> tuple[LiveDjangoBookingApi, list[FakeBrowser]]:
    api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused", VirtualUserAccountPool(account_count, "pw", "QA123"),
                               transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    browsers: list[FakeBrowser] = []

    @asynccontextmanager
    async def open_fake_browser(user_agent):
        browser_instance = FakeBrowser(len(browsers) + 1, user_agent, page_factory)
        browsers.append(browser_instance)
        try:
            yield browser_instance
        finally:
            browser_instance.is_closed = True

    api.browser_opener = open_fake_browser
    return api, browsers


def test_live_api_runs_browser_plans_through_screens(monkeypatch):
    api, browsers = build_live_api(FakeBrowserPage)
    results = send_virtual_user_traffic(api, [build_plan()], 10)

    assert results[0].session_key == "attempt-77" and not results[0].is_error
    assert len(results[0].capture_frames) == 5 and api.virtual_user_capacity() == 2  # 계정 반환
    assert len(browsers) == 1 and browsers[0].is_closed and browsers[0].blocked_trace_flags == [False]  # 봇 C = 흔적 그대로
    assert DEVICE_COOKIE_NAME not in browsers[0].pages[0].cookies  # 기기 공유 없음


def test_live_api_reports_missing_browser_without_stopping_run():
    api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused", VirtualUserAccountPool(1, "pw", "QA123"))

    @asynccontextmanager
    async def missing_browser(user_agent):
        raise BrowserUnavailableError(browser.BROWSER_SETUP_HINT)
        yield  # noqa · 형식상 제너레이터

    api.browser_opener = missing_browser
    result = send_virtual_user_traffic(api, [build_plan()], 10)[0]

    assert result.is_error and result.failed_step.startswith("browser · 실행 환경 없음")
    assert api.virtual_user_capacity() == 1


def test_queue_timeout_in_browser_is_recorded_as_session_error():
    api, _ = build_live_api(lambda: FakeBrowserPage(is_queue_stuck=True))
    result = send_virtual_user_traffic(api, [build_plan()], 10)[0]

    assert result.is_error and result.failed_step == "browser heartbeat · QUEUE_TIMEOUT"


def test_browser_captures_are_saved_for_b3(tmp_path):
    result = send_virtual_user_traffic(build_live_api(FakeBrowserPage)[0], [build_plan()], 10)
    assert save_browser_captures(tmp_path, "run-1", [PlannedUser("qa-0001", ActorType.BOT_C)], result) == 5

    capture_dir = tmp_path / CAPTURE_FOLDER_NAME / "run-1"
    frames = load_capture_frames(tmp_path, "run-1")
    assert [frame.step for frame in frames][0] == "공연 상세" and frames[0].click_x == 80  # 160px 축소 화면 가운데
    assert (capture_dir / frames[0].image_file_name).read_bytes() == b"\x89PNG-fake"
    assert len(json.loads((capture_dir / CAPTURE_INDEX_FILE_NAME).read_text(encoding="utf-8"))) == 5
    assert save_browser_captures(None, "run-1", [PlannedUser("qa-0001", ActorType.BOT_C)], result) == 0  # 저장 폴더 없음 = 건너뜀


def test_captures_follow_b3_type_order_not_finish_order(tmp_path):
    """봇 C · 봇 D 함께 · B3 제목 = 봇 C · 봇 D 세션이 계획 앞이어도 봇 C 화면 저장"""
    planned_users = [PlannedUser("qa-0001", ActorType.BOT_D), PlannedUser("qa-0002", ActorType.BOT_C)]
    results = send_virtual_user_traffic(build_live_api(FakeBrowserPage)[0], [build_plan(), build_plan()], 10)
    results[1] = replace(results[1], capture_frames=results[1].capture_frames[:2])  # 봇 C 표시
    assert save_browser_captures(tmp_path, "run-1", planned_users, results) == 2


def test_planned_users_of_browser_type_run_in_browser():
    planned_users = [PlannedUser("qa-0001", ActorType.BOT_C), PlannedUser("qa-0002", ActorType.BOT_A),
                     PlannedUser("qa-0003", ActorType.BOT_D)]
    plans = build_planned_user_session_plans(planned_users, BotProfileRegistry(), random_seed=1)
    assert [plan.uses_browser for plan in plans] == [True, False, True]


def build_device_plans(window_count: int) -> list[VirtualUserSessionPlan]:
    """봇 D · 기기 1대당 창 3개 → 기기 묶기"""
    return assign_devices([build_plan(behavior=BOT_D_BEHAVIOR) for _ in range(window_count)])


def test_bot_d_windows_share_one_browser_and_device_cookie():
    api, browsers = build_live_api(FakeBrowserPage, account_count=6)
    results = send_virtual_user_traffic(api, build_device_plans(6), 10)

    assert not any(result.is_error for result in results)
    assert len(browsers) == 2 and all(browser_instance.is_closed for browser_instance in browsers)  # 기기 2대 = 브라우저 2개 · 다 쓰면 닫음
    for browser_instance in browsers:
        assert len(browser_instance.pages) == 3  # 브라우저 1개 = 계정별 창 3개
        first_cookie = f"device-cookie-{browser_instance.browser_number}-1"
        assert {page.cookies[DEVICE_COOKIE_NAME] for page in browser_instance.pages} == {first_cookie}
        assert browser_instance.blocked_trace_flags == [True] * 3  # 흔적 없음 봇 = 화면 이벤트 차단
        assert len({page.filled[browser.LOGIN_USERNAME] for page in browser_instance.pages}) == 3  # 창마다 다른 계정
    assert results[0].device_key == results[2].device_key != results[3].device_key
    assert api.virtual_user_capacity() == 6


def test_bot_d_browser_failure_marks_every_window_without_stopping_run():
    api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused", VirtualUserAccountPool(3, "pw", "QA123"))

    @asynccontextmanager
    async def missing_browser(user_agent):
        raise BrowserUnavailableError(browser.BROWSER_SETUP_HINT)
        yield  # noqa · 형식상 제너레이터

    api.browser_opener = missing_browser
    results = send_virtual_user_traffic(api, build_device_plans(3), 10)
    assert all(result.is_error and result.failed_step.startswith("browser · 실행 환경 없음") for result in results)
    assert api.virtual_user_capacity() == 3


def test_system_address_is_trusted_like_https_except_localhost():
    assert browser.build_trusted_origin("http://web:8000") == "http://web:8000"  # 컨테이너 안 시험 대상
    assert browser.build_trusted_origin("http://127.0.0.1:8000/") == ""  # localhost = 이미 보안 컨텍스트
    assert browser.build_trusted_origin("https://staging.example.com") == ""


class ScriptBrokenPage(FakeBrowserPage):
    """화면 스크립트 오류 · 로그인 폼이 주소로 제출됨"""

    async def click(self, selector: str):
        if selector == browser.LOGIN_SUBMIT:
            self.url = f"{BASE_URL}/login/?username=qa-user-0001&password=pw"
            return CLICK_POINT
        return await super().click(selector)

    async def wait_for(self, selector: str, timeout_ms: float) -> bool:
        return selector != browser.SHOW_LIST_READY


def test_login_reports_page_script_failure_separately():
    api, _ = build_live_api(ScriptBrokenPage)
    result = send_virtual_user_traffic(api, [build_plan()], 10)[0]
    assert result.is_error and result.failed_step == "browser login · BROWSER_SCRIPT_NOT_RUNNING"


class Error(Exception):
    """Playwright 일반 오류와 같은 이름"""


class SeatClickBrokenPage(FakeBrowserPage):
    async def click(self, selector: str):
        if selector.startswith("[data-seat="):
            raise Error("Locator.click: Timeout 15000ms exceeded.\nCall log:\n  - waiting for locator")
        return await super().click(selector)


def test_unexpected_browser_error_records_step_and_first_line():
    api, _ = build_live_api(SeatClickBrokenPage)
    result = send_virtual_user_traffic(api, [build_plan()], 10)[0]
    assert result.is_error and result.failed_step == "browser seat · Error · Timeout 15000ms exceeded."
    assert result.session_key == "attempt-77"  # 대기열 통과 뒤 · 예매 시도 번호 유지


class NavigatingPlaywrightPage:
    """확정 클릭 직후 · 완료 화면으로 넘어가는 순간의 Playwright 페이지"""

    def __init__(self, message: str) -> None:
        self.message = message

    def on(self, event, handler) -> None:
        pass

    async def evaluate(self, expression):
        raise Error(self.message)


def test_page_read_during_navigation_is_retried_not_failed():
    navigating = browser.PlaywrightBrowserPage(NavigatingPlaywrightPage(
        "Page.evaluate: Execution context was destroyed, most likely because of a navigation"))
    assert asyncio.run(navigating.evaluate(browser.IS_SELECTION_ERROR_SHOWN)) is None  # 다시 읽음 · 오류 아님

    broken = browser.PlaywrightBrowserPage(NavigatingPlaywrightPage("Page.evaluate: SyntaxError"))
    try:
        asyncio.run(broken.evaluate("1 +"))
    except Error:
        pass
    else:
        raise AssertionError("다른 오류는 그대로 올라가야 함")


def test_browser_cap_comes_from_setting():
    api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused", VirtualUserAccountPool(1, "pw", "QA123"), max_concurrent_browsers=6)

    async def read_slots():
        return api.find_browser_slots()

    browser_slots, window_slots = asyncio.run(read_slots())
    assert (browser_slots._value, window_slots._value) == (6, 18)  # 창 = 브라우저 × 3


def test_accounts_prefer_unused_and_restart_after_reset(monkeypatch):
    api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused", VirtualUserAccountPool(3, "pw", "QA123"),
                               SystemAdminAccount("manager", "manager"))
    first = api.acquire_account_number()
    api.free_account_numbers.append(first)
    assert api.acquire_account_number() == 2  # 반환된 1번보다 새 계정 먼저 · 회차 사이 재사용 최소화

    async def fake_reset():
        return None

    monkeypatch.setattr(api, "_reset_as_admin", fake_reset)
    assert api.reset_test_data() and api.virtual_user_capacity() == 3  # 초기화 = 진행 중 예매 없음 · 계정 처음부터


def test_sold_out_browser_account_is_not_reused():
    api, _ = build_live_api(lambda: FakeBrowserPage(hidden_sold_seat_ids={"C3", "C4", "C5", "C6"}))
    result = send_virtual_user_traffic(api, [build_plan(behavior=replace(BOT_C_BEHAVIOR, sold_out_retry_count=0))], 10)[0]
    assert result.booking_outcome is BookingOutcome.SOLD_OUT
    assert api.free_account_numbers == []  # 취소가 서버에 닿았는지 모름 · 다른 VU에 주지 않음
