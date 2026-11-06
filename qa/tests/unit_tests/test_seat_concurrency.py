"""좌석 동시성 · Mock 재고 경쟁 · 잠금 없는 Mock = FAIL 검출 · Live 확정 동시 전송 요청 형식"""
import asyncio
import json
from pathlib import Path

import httpx

from ticket_guard_qa.domain.enums import SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, RunConfig
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.system_targets.live_django_system import LiveDjangoBookingApi, VirtualUserAccountPool
from ticket_guard_qa.test_suites.seat_concurrency import SeatConcurrencySuite
from ticket_guard_qa.test_suites.suite_interface import SuiteContext
from ticket_guard_qa.traffic_generators.virtual_user_traffic import ALL_SEAT_IDS


def build_context(system_target) -> SuiteContext:
    return SuiteContext(
        run_id="run-test", run_config=RunConfig(TargetKind.FAKE, ("seat_concurrency",)), system_target=system_target,
        answer_key_repository=None, case_data_dir=Path("."), report_progress=lambda text, **fields: None,
    )


def failure_lines(message: str) -> list[str]:
    return [line for line in message.split(MESSAGE_LINE_SEPARATOR) if line.startswith(FAIL_LINE_PREFIX)]


def test_locked_inventory_passes_all_scenarios():
    result = SeatConcurrencySuite().run(build_context(build_fake_system_target()))
    assert result.outcome is SuiteOutcome.PASSED, result.message
    assert result.metrics == {
        "seat_concurrency_same_seat_booked_count": 1.0, "seat_concurrency_double_sold_count": 0.0,
        "seat_concurrency_general_sold_quantity": 28.0, "seat_concurrency_oversold_quantity": 0.0,
        "seat_concurrency_duplicate_booking_count": 0.0,
    }
    assert "같은 좌석 경쟁 A1 · A2 · 예매 1/20 · 먼저 팔림 19" in result.message
    assert "판매 28석 · 예매 7/7 · 잔여 부족 3" in result.message
    assert "참고: 좌석 점유 5분(E16) 측정 불가 · 점유 기능 없음" in result.message


def test_broken_lock_is_reported_as_oversell_and_duplicate_booking():
    system_target = build_fake_system_target()
    system_target.booking_api.state.is_seat_lock_broken = True
    result = SeatConcurrencySuite().run(build_context(system_target))
    assert result.outcome is SuiteOutcome.FAILED
    assert failure_lines(result.message)[:3] == [
        "FAIL: 같은 좌석 중복 판매 · 예매 20건", "FAIL: 자유석 초과 판매 12석", "FAIL: 확정 재전송 중복 예매 2건",
    ]


def test_sold_out_inventory_is_not_measurable():
    system_target = build_fake_system_target()
    system_target.booking_api.state.sold_seat_ids = set(ALL_SEAT_IDS)
    system_target.booking_api.state.remaining_quantity = 0
    result = SeatConcurrencySuite().run(build_context(system_target))
    assert result.outcome is SuiteOutcome.SKIPPED
    assert "참고: 자유석 수량 경쟁 측정 불가 · 잔여 0석 · 초기화 미설정" in result.message
    assert not failure_lines(result.message)


class ContendedDjango:
    """확정 응답만 흉내 · 첫 요청 예매 · 같은 시도 재요청 = 같은 예매 번호"""

    def __init__(self) -> None:
        self.confirms: list[dict] = []
        self.cancel_count = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/":
            return httpx.Response(200, headers={"set-cookie": "csrftoken=token-1; Path=/"})
        if request.url.path == "/captcha.png":
            return httpx.Response(200, content=b"png")
        body = json.loads(request.content)
        if body["action"] == "start":
            return httpx.Response(200, json={"id": "attempt-1", "stage": "queue"})
        if body["action"] == "heartbeat":
            return httpx.Response(200, json={"stage": "captcha"})
        if body["action"] == "verify":
            return httpx.Response(200, json={"stage": "select", "sold": ["A1"], "remaining": 12})
        if body["action"] == "confirm":
            self.confirms.append(body)
            return httpx.Response(200, json={"redirect": "/complete/TG-ABC/", "sequence": body["sequence"]})
        if body["action"] == "cancel":
            self.cancel_count += 1
        return httpx.Response(200, json={})


def test_live_resend_uses_increasing_sequences_and_returns_account():
    django = ContendedDjango()
    booking_api = LiveDjangoBookingApi("http://web:8000", "ticketguard", "unused",
                                       VirtualUserAccountPool(1, "qa-password", "QA123"),
                                       transport=httpx.MockTransport(django.handle))

    async def resend():
        contender = await booking_api.prepare_seat_contender("blue-hour")
        responses = await booking_api.send_confirms(contender, ("B1",), 1, repeat_count=2)
        await booking_api.release_seat_contender(contender)
        return contender, responses

    contender, responses = asyncio.run(resend())
    assert (contender.inventory.sold_seat_ids, contender.inventory.remaining_quantity) == (frozenset({"A1"}), 12)
    assert sorted(confirm["sequence"] for confirm in django.confirms) == [1, 2]
    assert [response.booking_id for response in responses] == ["TG-ABC", "TG-ABC"]
    assert django.cancel_count == 0  # 예매 완료 시도는 취소하지 않음
    assert booking_api.virtual_user_capacity() == 1  # 계정 반환 · 다음 시나리오에서 재사용
