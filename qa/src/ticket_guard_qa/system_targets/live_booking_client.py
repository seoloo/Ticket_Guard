"""Live 예매 흐름 · VU 한 명 = 시험 계정 하나 · 로그인 → 예매 시작 → 대기열 → 보안문자 → 좌석 선택 · HTTP만"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from ticket_guard_qa.system_targets.target_interfaces import HttpResult

CSRF_COOKIE_NAME = "csrftoken"
REQUEST_TIMEOUT_SEC = 5.0
QUEUE_POLL_INTERVAL_SEC = 1.0  # 예매 화면 heartbeat 주기와 같게
MAX_QUEUE_WAIT_SEC = 60.0  # 기본 대기 12초 + 여유
DEFAULT_SHOW_ID = "blue-hour"
TEST_ACCOUNT_PREFIX = "qa-user-"  # 시스템 web/qa_test_hooks.py 규칙 · 번호 4자리

STAGE_QUEUE = "queue"
STAGE_CAPTCHA = "captcha"
STAGE_SEAT_SELECTION = "select"


def build_test_account_username(account_number: int) -> str:
    return f"{TEST_ACCOUNT_PREFIX}{account_number:04d}"


class BookingFlowError(RuntimeError):
    """어느 단계에서 · 어떤 응답으로 멈췄는지"""

    def __init__(self, step: str, status_code: int, error_code: str | None) -> None:
        super().__init__(f"예매 흐름 중단 · {step} · HTTP {status_code} · {error_code or '-'}")
        self.step = step
        self.status_code = status_code
        self.error_code = error_code


@dataclass
class BookingFlowResult:
    username: str
    booking_attempt_id: str
    reached_stage: str
    step_latency_ms: dict[str, float] = field(default_factory=dict)  # 단계별 응답 시간 · 대기열은 기다린 시간 포함

    @property
    def total_latency_ms(self) -> float:
        return sum(self.step_latency_ms.values())


class LiveBookingClient:
    """예매 화면(static/app.js)이 보내는 요청과 같은 순서 · 같은 본문"""

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http_client = httpx.Client(base_url=base_url.rstrip("/"), timeout=REQUEST_TIMEOUT_SEC, transport=transport)
        self.page_instance_id = str(uuid.uuid4())  # 탭 하나
        self.page_view_id = str(uuid.uuid4())  # 화면 한 번 표시
        self.booking_attempt_id: str | None = None

    def close(self) -> None:
        self.http_client.close()

    def post_json(self, path: str, payload: dict[str, Any]) -> HttpResult:
        headers = {"X-CSRFToken": self.http_client.cookies.get(CSRF_COOKIE_NAME, "")}
        started_at = time.perf_counter()
        response = self.http_client.post(path, json=payload, headers=headers)
        latency_ms = (time.perf_counter() - started_at) * 1000
        try:
            body = response.json()
        except ValueError:
            body = {}
        return HttpResult(response.status_code, body if isinstance(body, dict) else {}, latency_ms)

    def login(self, username: str, password: str) -> HttpResult:
        self.http_client.get("/login/")  # csrftoken 쿠키 받기
        return self._expect_ok("login", self.post_json(
            "/api/action/", {"action": "login", "username": username, "password": password}
        ))

    def start_booking(self, show_id: str) -> HttpResult:
        result = self._expect_ok("start", self._post_action("start", showId=show_id))
        self.booking_attempt_id = result.body["id"]
        return result

    def wait_for_admission(self, poll_interval_sec: float = QUEUE_POLL_INTERVAL_SEC,
                           max_wait_sec: float = MAX_QUEUE_WAIT_SEC) -> HttpResult:
        """대기열 heartbeat · 보안문자 단계가 될 때까지"""
        deadline = time.monotonic() + max_wait_sec
        while True:
            result = self._expect_ok("heartbeat", self._post_action("heartbeat"))
            if result.body.get("stage") != STAGE_QUEUE:
                return result
            if time.monotonic() >= deadline:
                raise BookingFlowError("heartbeat", result.status_code, "QUEUE_TIMEOUT")
            time.sleep(poll_interval_sec)

    def pass_captcha(self, answer: str) -> HttpResult:
        """이미지 요청으로 문제 발급 → 정답 제출 · 정답은 시스템 테스트 훅 고정값"""
        image_response = self.http_client.get("/captcha.png", params={
            "pageId": self.page_instance_id, "attemptId": self.booking_attempt_id,
        })
        if image_response.status_code != 200:
            raise BookingFlowError("captcha_image", image_response.status_code, None)
        return self._expect_ok("verify", self._post_action("verify", answer=answer))

    def cancel_booking(self) -> None:
        """시험 끝 정리 · 계정당 진행 중 예매 1건 규칙 · 다음 Run에서 같은 계정 재사용"""
        if self.booking_attempt_id:
            self._post_action("cancel", reason="user_cancel")

    def run_until_seat_selection(self, username: str, password: str, captcha_answer: str,
                                 show_id: str = DEFAULT_SHOW_ID,
                                 poll_interval_sec: float = QUEUE_POLL_INTERVAL_SEC) -> BookingFlowResult:
        step_latency_ms = {"login": self.login(username, password).latency_ms,
                           "start": self.start_booking(show_id).latency_ms}
        queue_started_at = time.perf_counter()
        admission = self.wait_for_admission(poll_interval_sec)
        step_latency_ms["queue"] = (time.perf_counter() - queue_started_at) * 1000
        if admission.body.get("stage") != STAGE_CAPTCHA:
            raise BookingFlowError("heartbeat", admission.status_code, f"UNEXPECTED_STAGE_{admission.body.get('stage')}")
        verified = self.pass_captcha(captcha_answer)
        step_latency_ms["captcha"] = verified.latency_ms
        # TODO(1-c): 좌석 클릭 · 확정 · 봇 프로필 간격대로 이벤트 전송
        return BookingFlowResult(username, self.booking_attempt_id or "", verified.body.get("stage", ""), step_latency_ms)

    def _post_action(self, action: str, **fields: Any) -> HttpResult:
        return self.post_json("/api/action/", {
            "action": action, "pageId": self.page_instance_id, "pageViewId": self.page_view_id,
            "attemptId": self.booking_attempt_id, **fields,
        })

    @staticmethod
    def _expect_ok(step: str, result: HttpResult) -> HttpResult:
        if result.status_code != 200:
            raise BookingFlowError(step, result.status_code, result.body.get("code"))
        return result
