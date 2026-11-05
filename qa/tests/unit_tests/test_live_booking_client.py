"""Live 예매 흐름 · 시스템 없이 가짜 HTTP 응답으로 확인 · 순서 · 본문 · 실패 단계"""
import json

import httpx
import pytest

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE
from ticket_guard_qa.system_targets.live_booking_client import (
    BookingFlowError,
    LiveBookingClient,
    build_test_account_username,
)
from ticket_guard_qa.system_targets.live_django_system import (
    AccountPoolExhaustedError,
    LiveDjangoBookingApi,
    VirtualUserAccountPool,
)

BASE_URL = "http://web:8000"
PASSWORD = "qa-password"
CAPTCHA_ANSWER = "QA123"


class FakeDjango:
    """예매 서버 흉내 · 받은 요청 기록 · 대기열은 heartbeat 두 번째에 통과"""

    def __init__(self, login_status: int = 200) -> None:
        self.login_status = login_status
        self.actions: list[dict] = []
        self.heartbeat_count = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/":
            return httpx.Response(200, headers={"set-cookie": "csrftoken=token-1; Path=/"})
        if request.url.path == "/captcha.png":
            return httpx.Response(200, content=b"png")
        body = json.loads(request.content)
        self.actions.append({**body, "csrf": request.headers.get("x-csrftoken")})
        if body["action"] == "login":
            return httpx.Response(self.login_status, json={} if self.login_status == 200 else {"code": "LOGIN_FAILED"})
        if body["action"] == "start":
            return httpx.Response(200, json={"id": "attempt-1", "stage": "queue"})
        if body["action"] == "heartbeat":
            self.heartbeat_count += 1
            return httpx.Response(200, json={"id": "attempt-1", "stage": "queue" if self.heartbeat_count < 2 else "captcha"})
        if body["action"] == "verify":
            is_correct = body["answer"] == CAPTCHA_ANSWER
            return httpx.Response(200 if is_correct else 400, json={"stage": "select"} if is_correct else {"code": "CAPTCHA_WRONG"})
        return httpx.Response(400, json={"code": "UNKNOWN"})


def test_flow_reaches_seat_selection_in_browser_order():
    fake_django = FakeDjango()
    client = LiveBookingClient(BASE_URL, httpx.MockTransport(fake_django.handle))
    result = client.run_until_seat_selection("qa-user-0001", PASSWORD, CAPTCHA_ANSWER, poll_interval_sec=0)

    assert result.reached_stage == "select"
    assert result.booking_attempt_id == "attempt-1"
    assert [action["action"] for action in fake_django.actions] == ["login", "start", "heartbeat", "heartbeat", "verify"]
    assert all(action["csrf"] == "token-1" for action in fake_django.actions)
    verify_body = fake_django.actions[-1]
    assert (verify_body["attemptId"], verify_body["pageId"]) == ("attempt-1", client.page_instance_id)
    assert set(result.step_latency_ms) == {"login", "start", "queue", "captcha"}


def test_flow_reports_the_failed_step():
    client = LiveBookingClient(BASE_URL, httpx.MockTransport(FakeDjango().handle))
    with pytest.raises(BookingFlowError) as error:
        client.run_until_seat_selection("qa-user-0001", PASSWORD, "WRONG", poll_interval_sec=0)
    assert (error.value.step, error.value.error_code) == ("verify", "CAPTCHA_WRONG")


def test_each_virtual_user_takes_next_test_account():
    fake_django = FakeDjango()
    booking_api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused",
                                       VirtualUserAccountPool(2, PASSWORD, CAPTCHA_ANSWER),
                                       httpx.MockTransport(fake_django.handle))
    behavior = DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN]

    first = booking_api.start_virtual_user_session(behavior)
    fake_django.heartbeat_count = 1  # 두 번째 VU는 바로 통과
    second = booking_api.start_virtual_user_session(behavior)

    assert not first.is_error and not second.is_error
    logins = [action["username"] for action in fake_django.actions if action["action"] == "login"]
    assert logins == [build_test_account_username(1), build_test_account_username(2)] == ["qa-user-0001", "qa-user-0002"]
    with pytest.raises(AccountPoolExhaustedError):
        booking_api.start_virtual_user_session(behavior)


def test_login_failure_marks_session_as_error():
    booking_api = LiveDjangoBookingApi(BASE_URL, "ticketguard", "unused",
                                       VirtualUserAccountPool(1, "wrong", CAPTCHA_ANSWER),
                                       httpx.MockTransport(FakeDjango(login_status=401).handle))
    result = booking_api.start_virtual_user_session(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN])
    assert result.is_error
