"""Live 예매 흐름 · VU 한 명 = 시험 계정 하나 · 로그인 → 예매 시작 → 대기열 → 보안문자 → 좌석 클릭 → 확정 · HTTP만"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ticket_guard_qa.domain.enums import BookingOutcome
from ticket_guard_qa.domain.models import VirtualUserSessionPlan
from ticket_guard_qa.system_targets.target_interfaces import HttpResult

CSRF_COOKIE_NAME = "csrftoken"
REQUEST_TIMEOUT_SEC = 10.0  # 동시 VU 수백 명 · 개발 서버 응답이 늦어짐
QUEUE_POLL_INTERVAL_SEC = 1.0  # 예매 화면 heartbeat 주기와 같게
MAX_QUEUE_WAIT_SEC = 60.0  # 기본 대기 12초 + 여유
DEFAULT_SHOW_ID = "blue-hour"  # 지정석 공연 · A1 ~ J10
TEST_ACCOUNT_PREFIX = "qa-user-"  # 시스템 web/qa_test_hooks.py 규칙 · 번호 4자리
SEATS_PER_BOOKING = 2  # 시스템 한도 1 ~ 4석
MAX_CONFIRM_ATTEMPT_COUNT = 3  # 먼저 팔린 좌석 → 다른 좌석으로 다시
EVENT_ACCEPTED_STATUS_CODES = (200, 202)  # 202 = Kafka 전달 대기

STAGE_QUEUE = "queue"
STAGE_CAPTCHA = "captcha"
STAGE_SEAT_SELECTION = "select"
SEAT_SOLD_ERROR_CODE = "SEAT_SOLD"


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
    booking_outcome: BookingOutcome
    booked_seat_ids: tuple[str, ...] = ()
    step_latency_ms: dict[str, float] = field(default_factory=dict)  # 대기열 · 좌석 클릭은 기다린 시간 포함

    @property
    def total_latency_ms(self) -> float:
        return sum(self.step_latency_ms.values())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveBookingClient:
    """예매 화면(static/app.js)이 보내는 요청과 같은 순서 · 같은 본문 · VU 하나 = 클라이언트 하나"""

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.http_client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=REQUEST_TIMEOUT_SEC, transport=transport)
        self.page_instance_id = str(uuid.uuid4())  # 탭 하나
        self.page_view_id = str(uuid.uuid4())  # 화면 한 번 표시
        self.booking_attempt_id: str | None = None
        self.show_id = DEFAULT_SHOW_ID
        self.confirm_sequence = 0
        self.is_booked = False
        self.sent_event_ids: list[str] = []  # 받음(200 · 202) 응답 받은 이벤트만

    async def close(self) -> None:
        await self.http_client.aclose()

    async def post_json(self, path: str, payload: dict[str, Any]) -> HttpResult:
        headers = {"X-CSRFToken": self.http_client.cookies.get(CSRF_COOKIE_NAME, "")}
        started_at = time.perf_counter()
        response = await self.http_client.post(path, json=payload, headers=headers)
        latency_ms = (time.perf_counter() - started_at) * 1000
        try:
            body = response.json()
        except ValueError:
            body = {}
        return HttpResult(response.status_code, body if isinstance(body, dict) else {}, latency_ms)

    async def login(self, username: str, password: str) -> HttpResult:
        await self.http_client.get("/login/")  # csrftoken 쿠키 받기
        return self._expect_ok("login", await self.post_json(
            "/api/action/", {"action": "login", "username": username, "password": password}
        ))

    async def reset_test_data(self) -> HttpResult:
        """관리자 로그인 뒤 · 시스템 테스트 훅 /api/qa/reset/ (Issue #6)"""
        return self._expect_ok("reset", await self.post_json("/api/qa/reset/", {}))

    async def start_booking(self, show_id: str) -> HttpResult:
        self.show_id = show_id
        result = self._expect_ok("start", await self._post_action("start", showId=show_id))
        self.booking_attempt_id = result.body["id"]
        return result

    async def wait_for_admission(self, poll_interval_sec: float = QUEUE_POLL_INTERVAL_SEC,
                                 max_wait_sec: float = MAX_QUEUE_WAIT_SEC) -> HttpResult:
        """대기열 heartbeat · 보안문자 단계가 될 때까지"""
        deadline = time.monotonic() + max_wait_sec
        while True:
            result = self._expect_ok("heartbeat", await self._post_action("heartbeat"))
            if result.body.get("stage") != STAGE_QUEUE:
                return result
            if time.monotonic() >= deadline:
                raise BookingFlowError("heartbeat", result.status_code, "QUEUE_TIMEOUT")
            await asyncio.sleep(poll_interval_sec)

    async def pass_captcha(self, answer: str) -> HttpResult:
        """이미지 요청으로 문제 발급 → 정답 제출 · 정답은 시스템 테스트 훅 고정값"""
        image_response = await self.http_client.get("/captcha.png", params={
            "pageId": self.page_instance_id, "attemptId": self.booking_attempt_id,
        })
        if image_response.status_code != 200:
            raise BookingFlowError("captcha_image", image_response.status_code, None)
        return self._expect_ok("verify", await self._post_action("verify", answer=answer))

    async def click_seats(self, seat_ids: list[str], click_intervals_ms: tuple[float, ...]) -> None:
        """좌석 하나 = seat_select 이벤트 하나 · 행동 값 간격대로 · 탐지에 쓰이는 입력"""
        select_page_view_id = str(uuid.uuid4())
        for index, seat_id in enumerate(seat_ids):
            await asyncio.sleep(click_intervals_ms[index % len(click_intervals_ms)] / 1000)
            event_id = str(uuid.uuid4())
            result = await self.post_json("/api/events/", {
                "eventType": "seat_select", "eventId": event_id, "occurredAt": utc_now_iso(),
                "pageInstanceId": self.page_instance_id, "pageViewId": select_page_view_id,
                "showId": self.show_id, "scheduleId": f"{self.show_id}-evening",
                "details": {"seatId": seat_id, "selectedCount": index + 1},
            })
            if result.status_code not in EVENT_ACCEPTED_STATUS_CODES:
                raise BookingFlowError("seat_select", result.status_code, result.body.get("code"))
            self.sent_event_ids.append(event_id)
        await asyncio.sleep(click_intervals_ms[-1] / 1000)  # 마지막 클릭 → 확정 버튼

    async def post_confirm(self, seat_ids: list[str], quantity: int, sequence: int) -> HttpResult:
        """확정 요청 그대로 · 판단 없음 · 지정석 = 좌석 목록 · 자유석 = 빈 목록 + 수량"""
        result = await self._post_action("confirm", sequence=sequence, seats=seat_ids, quantity=quantity)
        if result.status_code == 200:
            self.is_booked = True
        return result

    async def confirm_seats(self, seat_ids: list[str]) -> HttpResult:
        """200 = 예매 완료 · 409 SEAT_SOLD = 먼저 팔림(본문 sold) · 그 외는 오류"""
        self.confirm_sequence += 1
        result = await self.post_confirm(seat_ids, len(seat_ids), self.confirm_sequence)
        if result.status_code == 200:
            return result
        if result.body.get("code") == SEAT_SOLD_ERROR_CODE:
            return result
        raise BookingFlowError("confirm", result.status_code, result.body.get("code"))

    async def cancel_booking(self) -> None:
        """시험 끝 정리 · 계정당 진행 중 예매 1건 규칙 · 다음 Run에서 같은 계정 재사용"""
        if self.booking_attempt_id and not self.is_booked:
            await self._post_action("cancel", reason="user_cancel")

    async def enter_seat_selection(self, username: str, password: str, captcha_answer: str, show_id: str,
                                   poll_interval_sec: float = QUEUE_POLL_INTERVAL_SEC) -> HttpResult:
        """로그인 → 예매 시작 → 대기열 → 보안문자 · 응답 본문 sold · remaining = 그 시점 재고"""
        await self.login(username, password)
        await self.start_booking(show_id)
        admission = await self.wait_for_admission(poll_interval_sec)
        if admission.body.get("stage") != STAGE_CAPTCHA:
            raise BookingFlowError("heartbeat", admission.status_code, f"UNEXPECTED_STAGE_{admission.body.get('stage')}")
        return await self.pass_captcha(captcha_answer)

    async def run_booking_flow(self, username: str, password: str, captcha_answer: str,
                               session_plan: VirtualUserSessionPlan, open_at_monotonic: float,
                               show_id: str = DEFAULT_SHOW_ID,
                               poll_interval_sec: float = QUEUE_POLL_INTERVAL_SEC) -> BookingFlowResult:
        """오픈 전 로그인 → 오픈 + 진입 지연 → 예매 시작 → … → 확정 · 팔린 좌석은 다른 좌석으로 다시"""
        step_latency_ms = {"login": (await self.login(username, password)).latency_ms}
        entry_at = open_at_monotonic + session_plan.entry_delay_ms / 1000
        await asyncio.sleep(max(entry_at - time.monotonic(), 0.0))

        step_latency_ms["start"] = (await self.start_booking(show_id)).latency_ms
        queue_started_at = time.perf_counter()
        admission = await self.wait_for_admission(poll_interval_sec)
        step_latency_ms["queue"] = (time.perf_counter() - queue_started_at) * 1000
        if admission.body.get("stage") != STAGE_CAPTCHA:
            raise BookingFlowError("heartbeat", admission.status_code, f"UNEXPECTED_STAGE_{admission.body.get('stage')}")
        step_latency_ms["captcha"] = (await self.pass_captcha(captcha_answer)).latency_ms

        sold_seat_ids: set[str] = set()
        step_latency_ms["seat_select"] = step_latency_ms["confirm"] = 0.0
        for _ in range(MAX_CONFIRM_ATTEMPT_COUNT):
            seat_ids = [seat for seat in session_plan.preferred_seat_ids if seat not in sold_seat_ids][:SEATS_PER_BOOKING]
            if not seat_ids:
                break
            click_started_at = time.perf_counter()
            await self.click_seats(seat_ids, session_plan.click_intervals_ms)
            step_latency_ms["seat_select"] += (time.perf_counter() - click_started_at) * 1000
            confirmed = await self.confirm_seats(seat_ids)
            step_latency_ms["confirm"] += confirmed.latency_ms
            if self.is_booked:
                return BookingFlowResult(username, self.booking_attempt_id or "", BookingOutcome.BOOKED,
                                         tuple(seat_ids), step_latency_ms)
            sold_seat_ids.update(confirmed.body.get("sold") or seat_ids)  # 시스템이 준 판매 목록 · 없으면 고른 좌석 제외
        return BookingFlowResult(username, self.booking_attempt_id or "", BookingOutcome.SOLD_OUT, (), step_latency_ms)

    async def _post_action(self, action: str, **fields: Any) -> HttpResult:
        return await self.post_json("/api/action/", {
            "action": action, "pageId": self.page_instance_id, "pageViewId": self.page_view_id,
            "attemptId": self.booking_attempt_id, **fields,
        })

    @staticmethod
    def _expect_ok(step: str, result: HttpResult) -> HttpResult:
        if result.status_code != 200:
            raise BookingFlowError(step, result.status_code, result.body.get("code"))
        return result
