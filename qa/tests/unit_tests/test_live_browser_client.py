"""Live 브라우저 예매 흐름 · 브라우저 없이 가짜 페이지로 확인 · 단계 순서 · 캡처 · 매진 재시도 · 실행 환경 없음"""
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
from ticket_guard_qa.system_targets.live_django_system import LiveDjangoBookingApi, VirtualUserAccountPool
from ticket_guard_qa.traffic_generators.virtual_user_traffic import (
    build_planned_user_session_plans,
    save_browser_captures,
    send_virtual_user_traffic,
)

BASE_URL = "http://web:8000"
BOT_C_BEHAVIOR = replace(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_C], sold_out_retry_delay_ms=0)
CLICK_POINT = (640.0, 400.0)


class FakeBrowserPage:
    """예매 화면 흉내 · 클릭 순서 기록 · 먼저 팔린 좌석은 확정 때 드러남"""

    def __init__(self, hidden_sold_seat_ids: set[str] | None = None, is_queue_stuck: bool = False) -> None:
        self.url = ""
        self.clicks: list[str] = []
        self.filled: dict[str, str] = {}
        self.visited: list[str] = []
        self.hidden_sold_seat_ids = set(hidden_sold_seat_ids or ())
        self.shown_sold_seat_ids: set[str] = set()
        self.chosen_seat_ids: list[str] = []
        self.is_selection_error_shown = False
        self.is_queue_stuck = is_queue_stuck

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
        elif selector.startswith("[data-seat="):
            self.chosen_seat_ids.append(selector.split('"')[1])
            self.is_selection_error_shown = False
        elif selector == browser.CONFIRM_BOOKING:
            sold = self.hidden_sold_seat_ids.intersection(self.chosen_seat_ids)
            if sold:
                self.shown_sold_seat_ids |= sold
                self.is_selection_error_shown = True
            else:
                self.url = f"{BASE_URL}/complete/TG-1/"
            self.chosen_seat_ids = []
        return CLICK_POINT

    async def fill(self, selector: str, value: str) -> None:
        self.filled[selector] = value

    async def wait_for(self, selector: str, timeout_ms: float) -> bool:
        return not (self.is_queue_stuck and selector == browser.CAPTCHA_INPUT)

    async def evaluate(self, expression: str):
        if expression == browser.READ_ATTEMPT_ID:
            return "attempt-77"
        if expression == browser.READ_SOLD_SEATS:
            return sorted(self.shown_sold_seat_ids)
        if expression == browser.IS_SELECTION_ERROR_SHOWN:
            return self.is_selection_error_shown
        raise AssertionError(expression)

    async def screenshot(self) -> bytes:
        return b"\x89PNG-fake"


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


def test_browser_flow_gives_up_when_retry_count_is_zero():
    page = FakeBrowserPage(hidden_sold_seat_ids={"C3"})
    result = run_flow(page, build_plan(behavior=replace(BOT_C_BEHAVIOR, sold_out_retry_count=0)))

    assert result.booking_outcome is BookingOutcome.SOLD_OUT
    assert page.clicks[-1] == browser.CANCEL_BOOKING  # 계정 정리


def build_live_api(page_factory) -> LiveDjangoBookingApi:
    api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused", VirtualUserAccountPool(2, "pw", "QA123"),
                               transport=httpx.MockTransport(lambda request: httpx.Response(500)))

    @asynccontextmanager
    async def open_page(user_agent):
        yield page_factory()

    api.browser_page_opener = open_page
    return api


def test_live_api_runs_browser_plans_through_screens(monkeypatch):
    api = build_live_api(FakeBrowserPage)
    results = send_virtual_user_traffic(api, [build_plan()], 10)

    assert results[0].session_key == "attempt-77" and not results[0].is_error
    assert len(results[0].capture_frames) == 5 and api.virtual_user_capacity() == 2  # 계정 반환


def test_live_api_reports_missing_browser_without_stopping_run():
    api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused", VirtualUserAccountPool(1, "pw", "QA123"))

    @asynccontextmanager
    async def missing_browser(user_agent):
        raise BrowserUnavailableError(browser.BROWSER_SETUP_HINT)
        yield  # noqa · 형식상 제너레이터

    api.browser_page_opener = missing_browser
    result = send_virtual_user_traffic(api, [build_plan()], 10)[0]

    assert result.is_error and result.failed_step.startswith("browser · 실행 환경 없음")
    assert api.virtual_user_capacity() == 1


def test_queue_timeout_in_browser_is_recorded_as_session_error():
    api = build_live_api(lambda: FakeBrowserPage(is_queue_stuck=True))
    result = send_virtual_user_traffic(api, [build_plan()], 10)[0]

    assert result.is_error and result.failed_step == "browser heartbeat · QUEUE_TIMEOUT"


def test_browser_captures_are_saved_for_b3(tmp_path):
    result = send_virtual_user_traffic(build_live_api(FakeBrowserPage), [build_plan()], 10)
    assert save_browser_captures(tmp_path, "run-1", result) == 5

    capture_dir = tmp_path / CAPTURE_FOLDER_NAME / "run-1"
    frames = load_capture_frames(tmp_path, "run-1")
    assert [frame.step for frame in frames][0] == "공연 상세" and frames[0].click_x == 80  # 160px 축소 화면 가운데
    assert (capture_dir / frames[0].image_file_name).read_bytes() == b"\x89PNG-fake"
    assert len(json.loads((capture_dir / CAPTURE_INDEX_FILE_NAME).read_text(encoding="utf-8"))) == 5
    assert save_browser_captures(None, "run-1", result) == 0  # 저장 폴더 없음 = 건너뜀


def test_planned_users_of_browser_type_run_in_browser():
    planned_users = [PlannedUser("qa-0001", ActorType.BOT_C), PlannedUser("qa-0002", ActorType.BOT_A)]
    plans = build_planned_user_session_plans(planned_users, BotProfileRegistry(), random_seed=1)
    assert [plan.uses_browser for plan in plans] == [True, False]
