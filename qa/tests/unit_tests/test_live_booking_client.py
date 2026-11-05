"""Live 예매 흐름 · 시스템 없이 가짜 HTTP 응답으로 확인 · 순서 · 본문 · 실패 단계 · 동시 실행"""
import asyncio
import json
import time
from dataclasses import replace

import httpx
import pytest

from ticket_guard_qa.domain.enums import ActorType, BookingOutcome, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import RunConfig, SessionKey, VirtualUserSessionPlan, VirtualUserSessionResult
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.system_targets.live_booking_client import (
    BookingFlowError,
    LiveBookingClient,
    build_test_account_username,
)
from ticket_guard_qa.system_targets.live_django_system import (
    LiveDjangoBookingApi,
    SystemAdminAccount,
    VirtualUserAccountPool,
)
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError
from ticket_guard_qa.test_suites.booking_flow import BookingFlowSuite, find_double_sold_seat_ids
from ticket_guard_qa.test_suites.suite_interface import SuiteContext
from ticket_guard_qa.traffic_generators import virtual_user_traffic
from ticket_guard_qa.traffic_generators.virtual_user_traffic import (
    ALL_SEAT_IDS,
    TIMEOUT_FAILED_STEP,
    build_session_plans,
    send_virtual_user_traffic,
)

BASE_URL = "http://web:8000"
PASSWORD = "qa-password"
CAPTCHA_ANSWER = "QA123"
HUMAN_BEHAVIOR = DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN]


def build_instant_plan(preferred_seat_ids: tuple[str, ...] = ALL_SEAT_IDS) -> VirtualUserSessionPlan:
    return VirtualUserSessionPlan(HUMAN_BEHAVIOR, 0.0, (0.0, 0.0, 0.0), preferred_seat_ids)


class FakeDjango:
    """예매 서버 흉내 · 받은 요청 기록 · heartbeat n번째에 입장 · 좌석 판매 상태"""

    def __init__(self, login_status: int = 200, admit_on_heartbeat: int = 2, sold_seat_ids: set[str] | None = None) -> None:
        self.login_status = login_status
        self.admit_on_heartbeat = admit_on_heartbeat
        self.sold_seat_ids = set(sold_seat_ids or ())
        self.actions: list[dict] = []
        self.events: list[dict] = []
        self.reset_count = 0
        self.heartbeat_count = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/":
            return httpx.Response(200, headers={"set-cookie": "csrftoken=token-1; Path=/"})
        if request.url.path == "/captcha.png":
            return httpx.Response(200, content=b"png")
        if request.url.path == "/api/qa/reset/":
            self.reset_count += 1
            return httpx.Response(200, json={"ok": True})
        body = json.loads(request.content)
        if request.url.path == "/api/events/":
            self.events.append(body)
            return httpx.Response(202, json={"accepted": True, "state": "queued"})
        self.actions.append({**body, "csrf": request.headers.get("x-csrftoken")})
        if body["action"] == "login":
            return httpx.Response(self.login_status, json={} if self.login_status == 200 else {"code": "LOGIN_FAILED"})
        if body["action"] == "start":
            return httpx.Response(200, json={"id": "attempt-1", "stage": "queue"})
        if body["action"] == "heartbeat":
            self.heartbeat_count += 1
            is_admitted = self.heartbeat_count >= self.admit_on_heartbeat
            return httpx.Response(200, json={"id": "attempt-1", "stage": "captcha" if is_admitted else "queue"})
        if body["action"] == "cancel":
            return httpx.Response(200, json={"stage": "cancelled"})
        if body["action"] == "verify":
            is_correct = body["answer"] == CAPTCHA_ANSWER
            return httpx.Response(200 if is_correct else 400, json={"stage": "select"} if is_correct else {"code": "CAPTCHA_WRONG"})
        if body["action"] == "confirm":
            if self.sold_seat_ids.intersection(body["seats"]):
                return httpx.Response(409, json={"code": "SEAT_SOLD", "sold": sorted(self.sold_seat_ids)})
            self.sold_seat_ids.update(body["seats"])
            return httpx.Response(200, json={"redirect": "/complete/TG-1/", "sequence": body["sequence"]})
        return httpx.Response(400, json={"code": "UNKNOWN"})


def build_booking_api(fake_django: FakeDjango, account_count: int = 2, captcha_answer: str = CAPTCHA_ANSWER,
                      admin_account: SystemAdminAccount | None = None) -> LiveDjangoBookingApi:
    return LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused",
                                VirtualUserAccountPool(account_count, PASSWORD, captcha_answer),
                                admin_account, httpx.MockTransport(fake_django.handle))


async def run_flow(client: LiveBookingClient, plan: VirtualUserSessionPlan, captcha_answer: str = CAPTCHA_ANSWER):
    try:
        return await client.run_booking_flow("qa-user-0001", PASSWORD, captcha_answer, plan, time.monotonic(),
                                             poll_interval_sec=0)
    finally:
        await client.close()


@pytest.fixture(autouse=True)
def open_immediately(monkeypatch):
    monkeypatch.setattr(virtual_user_traffic, "PRE_OPEN_LOGIN_SEC", 0.0)  # 시험에서는 오픈 대기 없음


def test_flow_books_seats_in_browser_order():
    fake_django = FakeDjango()
    client = LiveBookingClient(BASE_URL, httpx.MockTransport(fake_django.handle))
    result = asyncio.run(run_flow(client, build_instant_plan(("C3", "C4", "C5"))))

    assert (result.booking_outcome, result.booked_seat_ids) == (BookingOutcome.BOOKED, ("C3", "C4"))
    assert [action["action"] for action in fake_django.actions] == ["login", "start", "heartbeat", "heartbeat", "verify", "confirm"]
    assert all(action["csrf"] == "token-1" for action in fake_django.actions)
    assert [(event["eventType"], event["details"]) for event in fake_django.events] == [
        ("seat_select", {"seatId": "C3", "selectedCount": 1}), ("seat_select", {"seatId": "C4", "selectedCount": 2}),
    ]
    assert fake_django.events[0]["scheduleId"] == "blue-hour-evening"
    confirm_body = fake_django.actions[-1]
    assert (confirm_body["seats"], confirm_body["sequence"], confirm_body["pageId"]) == (["C3", "C4"], 1, client.page_instance_id)
    assert set(result.step_latency_ms) == {"login", "start", "queue", "captcha", "seat_select", "confirm"}


def test_sold_seats_are_skipped_then_sold_out():
    fake_django = FakeDjango(sold_seat_ids={"C3"})
    client = LiveBookingClient(BASE_URL, httpx.MockTransport(fake_django.handle))
    retried = asyncio.run(run_flow(client, build_instant_plan(("C3", "C4", "C5", "C6"))))
    assert retried.booked_seat_ids == ("C4", "C5")  # 첫 확정 409 → 팔린 좌석 빼고 다시

    sold_out_django = FakeDjango(sold_seat_ids=set(ALL_SEAT_IDS))
    sold_out_client = LiveBookingClient(BASE_URL, httpx.MockTransport(sold_out_django.handle))
    sold_out = asyncio.run(run_flow(sold_out_client, build_instant_plan()))
    assert sold_out.booking_outcome is BookingOutcome.SOLD_OUT
    assert sum(action["action"] == "confirm" for action in sold_out_django.actions) == 1  # 남은 좌석 없음 → 멈춤


def test_flow_reports_the_failed_step():
    client = LiveBookingClient(BASE_URL, httpx.MockTransport(FakeDjango().handle))
    with pytest.raises(BookingFlowError) as error:
        asyncio.run(run_flow(client, build_instant_plan(), captcha_answer="WRONG"))
    assert (error.value.step, error.value.error_code) == ("verify", "CAPTCHA_WRONG")


def test_virtual_users_run_together_with_own_accounts():
    fake_django = FakeDjango(admit_on_heartbeat=1)
    booking_api = build_booking_api(fake_django, account_count=2)
    results = send_virtual_user_traffic(booking_api, [build_instant_plan(("A1", "A2")), build_instant_plan(("B1", "B2"))], 10)

    assert [result.booking_outcome for result in results] == [BookingOutcome.BOOKED, BookingOutcome.BOOKED]
    logins = sorted(action["username"] for action in fake_django.actions if action["action"] == "login")
    assert logins == [build_test_account_username(1), build_test_account_username(2)] == ["qa-user-0001", "qa-user-0002"]
    assert not any(action["action"] == "cancel" for action in fake_django.actions)  # 확정한 계정은 취소 없음
    with pytest.raises(AccountPoolExhaustedError):
        send_virtual_user_traffic(booking_api, [build_instant_plan()], 10)


def test_failed_session_cancels_to_return_account():
    fake_django = FakeDjango(admit_on_heartbeat=1)
    results = send_virtual_user_traffic(build_booking_api(fake_django, captcha_answer="WRONG"), [build_instant_plan()], 10)
    assert results[0].is_error and results[0].failed_step == "verify · CAPTCHA_WRONG"
    assert results[0].session_key == "attempt-1"  # 이벤트를 보낸 세션 · 정답표에 연결
    assert fake_django.actions[-1]["action"] == "cancel"


def test_login_failure_marks_session_as_error():
    booking_api = build_booking_api(FakeDjango(login_status=401), account_count=1)
    results = send_virtual_user_traffic(booking_api, [build_instant_plan()], 10)
    assert results[0].is_error
    assert results[0].failed_step == "login · LOGIN_FAILED"


def test_reset_needs_admin_account():
    fake_django = FakeDjango()
    assert build_booking_api(fake_django).reset_test_data() is False
    assert build_booking_api(fake_django, admin_account=SystemAdminAccount("manager", "secret")).reset_test_data() is True
    assert fake_django.reset_count == 1
    assert fake_django.actions[-1]["username"] == "manager"


class SlowBookingApi:
    """첫 VU만 바로 끝남 · 나머지는 시험 시간보다 오래 걸림"""

    def virtual_user_capacity(self) -> int | None:
        return None

    def reset_test_data(self) -> bool:
        return True

    async def run_virtual_user_session(self, session_plan, open_at_monotonic) -> VirtualUserSessionResult:
        if session_plan.preferred_seat_ids[0] != "A1":
            await asyncio.sleep(10)
        return VirtualUserSessionResult(SessionKey("attempt-fast"), 1.0, is_error=False, booking_outcome=BookingOutcome.BOOKED)


def test_time_limit_marks_unfinished_users():
    plans = [build_instant_plan(("A1",)), build_instant_plan(("B1",))]
    results = send_virtual_user_traffic(SlowBookingApi(), plans, time_limit_sec=0.2)
    assert not results[0].is_error
    assert (results[1].is_error, results[1].failed_step) == (True, TIMEOUT_FAILED_STEP)


def test_session_plans_follow_behavior_and_seed():
    bot_behavior = DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A]
    plans = build_session_plans([HUMAN_BEHAVIOR, bot_behavior], random_seed=7)
    assert plans == build_session_plans([HUMAN_BEHAVIOR, bot_behavior], random_seed=7)  # 같은 시드 = 같은 계획
    assert max(plans[1].click_intervals_ms) < min(plans[0].click_intervals_ms)  # 봇 A 간격 80ms · 사람 1200ms
    assert sorted(plans[0].preferred_seat_ids) == sorted(ALL_SEAT_IDS)


def test_double_sold_seats_are_found():
    results = [
        VirtualUserSessionResult(SessionKey("a"), 1.0, False, booked_seat_ids=("A1", "A2")),
        VirtualUserSessionResult(SessionKey("b"), 1.0, False, booked_seat_ids=("A2", "A3")),
    ]
    assert find_double_sold_seat_ids(results) == ["A2"]


def build_booking_flow_context(system_target, virtual_user_count: int) -> SuiteContext:
    return SuiteContext(
        run_id="run-test",
        run_config=RunConfig(TargetKind.LIVE, ("booking_flow",), virtual_user_count=virtual_user_count),
        system_target=system_target,
        answer_key_repository=None,
        case_data_dir=None,
        report_progress=lambda text, **fields: None,
    )


def test_booking_flow_suite_passes_on_mock():
    result = BookingFlowSuite().run(build_booking_flow_context(build_fake_system_target(), 30))
    assert result.outcome is SuiteOutcome.PASSED, result.message
    assert result.metrics["booking_flow_booked_count"] == 30
    assert result.message.startswith("예매 완료 30 · 매진 0 · 오류 0 / VU 30")


def test_booking_flow_suite_reports_failed_step():
    booking_api = build_booking_api(FakeDjango(admit_on_heartbeat=1), account_count=2, captcha_answer="WRONG")
    system_target = replace(build_fake_system_target(), booking_api=booking_api)
    result = BookingFlowSuite().run(build_booking_flow_context(system_target, 2))
    assert result.outcome is SuiteOutcome.FAILED
    assert "verify · CAPTCHA_WRONG 2건" in result.message and "초기화 건너뜀" in result.message
    assert result.metrics["booking_flow_failure_count"] == 2


def test_booking_flow_suite_fails_on_account_shortage():
    system_target = replace(build_fake_system_target(), booking_api=build_booking_api(FakeDjango(), account_count=2))
    result = BookingFlowSuite().run(build_booking_flow_context(system_target, 3))
    assert result.outcome is SuiteOutcome.FAILED
    assert "시험 계정 부족 · VU 3명 · 계정 2개" in result.message
