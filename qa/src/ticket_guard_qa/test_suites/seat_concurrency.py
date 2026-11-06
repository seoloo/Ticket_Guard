"""좌석 동시성 · 좌석 선택 단계 대기 VU → 확정 동시 전송 · 같은 좌석 · 자유석 수량 · 확정 재전송 · E12 · E20"""
import asyncio
from collections import Counter
from dataclasses import dataclass, field

import httpx

from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, REFERENCE_LINE_PREFIX, SuiteResult
from ticket_guard_qa.system_targets.live_booking_client import BookingFlowError
from ticket_guard_qa.system_targets.target_interfaces import (
    AccountPoolExhaustedError,
    BookingApi,
    ConfirmResponse,
    SeatContender,
)
from ticket_guard_qa.test_suites.suite_interface import SuiteContext
from ticket_guard_qa.traffic_generators.virtual_user_traffic import ALL_SEAT_IDS, reset_before_traffic

RESERVED_SHOW_ID = "blue-hour"  # 지정석 · 지정석 공연끼리 판매 좌석 공유
GENERAL_SHOW_ID = "open-air"  # 자유석 · 자유석 공연끼리 잔여 수량 공유
SAME_SEAT_CONTENDER_COUNT = 20
CONTESTED_SEAT_COUNT = 2
GENERAL_QUANTITY_PER_BOOKING = 4  # 시스템 한도 1 ~ 4석
INITIAL_GENERAL_QUANTITY = 28  # 시스템 초기 잔여 수량 · VU 수 계산용 · 실제 판정은 응답 재고 기준
EXTRA_GENERAL_CONTENDER_COUNT = 3  # 잔여 수량보다 많은 요청 · 초과분 = 잔여 부족 응답
RESEND_COUNT = 2  # 더블 클릭
MIN_CONTENDER_COUNT = 2
SEAT_SOLD_ERROR_CODE = "SEAT_SOLD"
INSUFFICIENT_STOCK_ERROR_CODE = "INSUFFICIENT_STOCK"
CONNECTION_ERROR_STATUS = 0
SEAT_HOLD_NOT_MEASURABLE = "좌석 점유 5분(E16) 측정 불가 · 점유 기능 없음"


@dataclass
class ScenarioReport:
    is_measured: bool = True
    info_lines: list[str] = field(default_factory=list)
    failure_lines: list[str] = field(default_factory=list)
    reference_lines: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


def describe_error(error: BaseException) -> str:
    if isinstance(error, BookingFlowError):
        return f"{error.step} · {error.error_code or error.status_code}"
    if isinstance(error, httpx.HTTPError):
        return f"connection · {type(error).__name__}"
    return f"qa · {type(error).__name__}"


def count_codes(responses: list[ConfirmResponse]) -> Counter:
    return Counter("200" if response.status_code == 200 else response.error_code or str(response.status_code)
                   for response in responses)


def add_unexpected_responses(report: ScenarioReport, responses: list[ConfirmResponse], expected_codes: set[str]) -> None:
    """연결 오류 = 참고 · 기대 밖 응답 코드 = FAIL"""
    connection_errors = [response for response in responses if response.status_code == CONNECTION_ERROR_STATUS]
    if connection_errors:
        report.reference_lines.append(f"확정 연결 오류 {len(connection_errors)}건")
    unexpected = Counter(
        response.error_code or str(response.status_code) for response in responses
        if response.status_code not in (200, CONNECTION_ERROR_STATUS) and response.error_code not in expected_codes
    )
    report.failure_lines.extend(f"확정 응답 오류 {code} {count}건" for code, count in unexpected.most_common())


async def prepare_contenders(
    booking_api: BookingApi, show_id: str, count: int
) -> tuple[list[SeatContender], Counter]:
    """좌석 선택 단계까지 동시 준비 · 준비 실패는 참여 제외"""
    capacity = booking_api.virtual_user_capacity()
    count = min(count, capacity) if capacity is not None else count
    results = await asyncio.gather(
        *(booking_api.prepare_seat_contender(show_id) for _ in range(count)), return_exceptions=True
    )
    contenders = [result for result in results if isinstance(result, SeatContender)]
    errors = Counter(describe_error(result) for result in results if isinstance(result, BaseException))
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, Exception):
            raise result  # 취소 · 종료 신호
    return contenders, errors


def add_preparation_errors(report: ScenarioReport, errors: Counter) -> None:
    report.reference_lines.extend(f"준비 실패 {step} {count}건" for step, count in errors.most_common())


async def release_contenders(booking_api: BookingApi, contenders: list[SeatContender]) -> None:
    await asyncio.gather(*(booking_api.release_seat_contender(contender) for contender in contenders),
                         return_exceptions=True)


def not_measured(report: ScenarioReport, reason: str) -> ScenarioReport:
    report.is_measured = False
    report.reference_lines.append(reason)
    return report


async def run_same_seat_scenario(booking_api: BookingApi) -> ScenarioReport:
    """VU 20명 · 같은 지정석 2석 동시 확정 → 예매 1건 · 나머지 먼저 팔림 · E12"""
    report = ScenarioReport()
    contenders, errors = await prepare_contenders(booking_api, RESERVED_SHOW_ID, SAME_SEAT_CONTENDER_COUNT)
    add_preparation_errors(report, errors)
    try:
        if len(contenders) < MIN_CONTENDER_COUNT:
            return not_measured(report, f"같은 좌석 경쟁 측정 불가 · 준비된 VU {len(contenders)}명")
        sold_seat_ids = frozenset().union(*(contender.inventory.sold_seat_ids for contender in contenders))
        seat_ids = tuple(seat for seat in ALL_SEAT_IDS if seat not in sold_seat_ids)[:CONTESTED_SEAT_COUNT]
        if len(seat_ids) < CONTESTED_SEAT_COUNT:
            return not_measured(report, "같은 좌석 경쟁 측정 불가 · 빈 지정석 2석 미만 · 초기화 미설정")
        response_lists = await asyncio.gather(
            *(booking_api.send_confirms(contender, seat_ids, len(seat_ids)) for contender in contenders)
        )
    finally:
        await release_contenders(booking_api, contenders)

    responses = [response for response_list in response_lists for response in response_list]
    codes = count_codes(responses)
    booked_count = codes["200"]
    report.info_lines.append(
        f"같은 좌석 경쟁 {' · '.join(seat_ids)} · 예매 {booked_count}/{len(contenders)} · 먼저 팔림 {codes[SEAT_SOLD_ERROR_CODE]}"
    )
    if booked_count > 1:
        report.failure_lines.append(f"같은 좌석 중복 판매 · 예매 {booked_count}건")
    if booked_count == 0 and not any(response.status_code == CONNECTION_ERROR_STATUS for response in responses):
        report.failure_lines.append("같은 좌석 예매 0건 · 빈 좌석 미판매")
    add_unexpected_responses(report, responses, {SEAT_SOLD_ERROR_CODE})
    report.metrics = {
        "seat_concurrency_same_seat_booked_count": float(booked_count),
        "seat_concurrency_double_sold_count": float(max(booked_count - 1, 0)),
    }
    return report


async def run_general_stock_scenario(booking_api: BookingApi) -> ScenarioReport:
    """자유석 · 잔여 수량보다 많은 VU가 4석씩 동시 확정 → 판매 합계 ≤ 잔여 · 잔여 음수 0 · E12"""
    report = ScenarioReport()
    max_bookings = -(-INITIAL_GENERAL_QUANTITY // GENERAL_QUANTITY_PER_BOOKING)
    contenders, errors = await prepare_contenders(
        booking_api, GENERAL_SHOW_ID, max_bookings + EXTRA_GENERAL_CONTENDER_COUNT
    )
    add_preparation_errors(report, errors)
    try:
        if len(contenders) < MIN_CONTENDER_COUNT:
            return not_measured(report, f"자유석 수량 경쟁 측정 불가 · 준비된 VU {len(contenders)}명")
        remaining_before = min(contender.inventory.remaining_quantity for contender in contenders)
        if remaining_before < GENERAL_QUANTITY_PER_BOOKING:
            return not_measured(report, f"자유석 수량 경쟁 측정 불가 · 잔여 {remaining_before}석 · 초기화 미설정")
        response_lists = await asyncio.gather(*(
            booking_api.send_confirms(contender, (), GENERAL_QUANTITY_PER_BOOKING) for contender in contenders
        ))
    finally:
        await release_contenders(booking_api, contenders)

    responses = [response for response_list in response_lists for response in response_list]
    codes = count_codes(responses)
    booked_count = codes["200"]
    sold_quantity = booked_count * GENERAL_QUANTITY_PER_BOOKING
    expected_booked_count = min(len(contenders), remaining_before // GENERAL_QUANTITY_PER_BOOKING)
    oversold_quantity = max(sold_quantity - remaining_before, 0)
    report.info_lines.append(
        f"자유석 수량 경쟁 · 잔여 {remaining_before}석 · VU {len(contenders)} × {GENERAL_QUANTITY_PER_BOOKING}석"
    )
    report.info_lines.append(
        f"판매 {sold_quantity}석 · 예매 {booked_count}/{expected_booked_count} · 잔여 부족 {codes[INSUFFICIENT_STOCK_ERROR_CODE]}"
    )
    if oversold_quantity:
        report.failure_lines.append(f"자유석 초과 판매 {oversold_quantity}석")
    has_connection_error = any(response.status_code == CONNECTION_ERROR_STATUS for response in responses)
    if booked_count < expected_booked_count and not has_connection_error:
        report.failure_lines.append(f"자유석 미판매 · 예매 {booked_count}/{expected_booked_count}건")
    reported_remaining = [response.remaining_quantity for response in responses
                          if response.error_code == INSUFFICIENT_STOCK_ERROR_CODE and response.remaining_quantity is not None]
    if any(remaining < 0 for remaining in reported_remaining):
        report.failure_lines.append(f"잔여 수량 음수 {min(reported_remaining)}석")
    elif reported_remaining and min(reported_remaining) != remaining_before - sold_quantity:
        report.failure_lines.append(
            f"잔여 수량 불일치 · 응답 {min(reported_remaining)}석 · 기대 {remaining_before - sold_quantity}석"
        )
    add_unexpected_responses(report, responses, {INSUFFICIENT_STOCK_ERROR_CODE})
    report.metrics = {
        "seat_concurrency_general_sold_quantity": float(sold_quantity),
        "seat_concurrency_oversold_quantity": float(oversold_quantity),
    }
    return report


async def run_resend_scenario(booking_api: BookingApi) -> ScenarioReport:
    """같은 확정 요청 동시 2회 · 더블 클릭 → 예매 1건 · 같은 예매 번호 · E20"""
    report = ScenarioReport()
    contenders, errors = await prepare_contenders(booking_api, RESERVED_SHOW_ID, 1)
    add_preparation_errors(report, errors)
    try:
        if not contenders:
            return not_measured(report, "확정 재전송 측정 불가 · 준비된 VU 0명")
        contender = contenders[0]
        seat_ids = tuple(seat for seat in ALL_SEAT_IDS if seat not in contender.inventory.sold_seat_ids)[:1]
        if not seat_ids:
            return not_measured(report, "확정 재전송 측정 불가 · 빈 지정석 없음 · 초기화 미설정")
        responses = await booking_api.send_confirms(contender, seat_ids, len(seat_ids), repeat_count=RESEND_COUNT)
    finally:
        await release_contenders(booking_api, contenders)

    booking_ids = {response.booking_id for response in responses if response.status_code == 200}
    accepted_count = sum(response.status_code == 200 for response in responses)
    report.info_lines.append(
        f"확정 재전송 {seat_ids[0]} · 요청 {RESEND_COUNT} · 응답 200 {accepted_count} · 예매 번호 {len(booking_ids)}개"
    )
    if len(booking_ids) > 1:
        report.failure_lines.append(f"확정 재전송 중복 예매 {len(booking_ids)}건")
    if not booking_ids and not any(response.status_code == CONNECTION_ERROR_STATUS for response in responses):
        report.failure_lines.append("확정 재전송 예매 0건")
    add_unexpected_responses(report, responses, {"STALE_REQUEST"})  # 재전송 거절도 중복 예매 아님
    report.metrics = {"seat_concurrency_duplicate_booking_count": float(max(len(booking_ids) - 1, 0))}
    return report



def build_message(reports: list[ScenarioReport], reset_message: str) -> str:
    lines = [FAIL_LINE_PREFIX + line for report in reports for line in report.failure_lines]
    lines += [line for report in reports for line in report.info_lines]
    lines += [REFERENCE_LINE_PREFIX + line for report in reports for line in report.reference_lines]
    lines.append(REFERENCE_LINE_PREFIX + SEAT_HOLD_NOT_MEASURABLE)
    if not reset_message.startswith("시험 데이터 초기화"):
        lines.append(REFERENCE_LINE_PREFIX + reset_message)
    return MESSAGE_LINE_SEPARATOR.join(lines)


class SeatConcurrencySuite:
    suite_name = "seat_concurrency"
    title = "좌석 동시성"
    related_codes: tuple[str, ...] = ("E12", "E16", "E20")

    def run(self, context: SuiteContext) -> SuiteResult:
        booking_api = context.system_target.booking_api
        reset_message = reset_before_traffic(booking_api)
        context.report_progress(reset_message)
        try:
            reports = asyncio.run(self.run_scenarios(booking_api, context))
        except AccountPoolExhaustedError as error:
            return SuiteResult(self.suite_name, SuiteOutcome.FAILED, message=FAIL_LINE_PREFIX + str(error))

        message = build_message(reports, reset_message)
        metrics = {name: value for report in reports for name, value in report.metrics.items()}
        if any(report.failure_lines for report in reports):
            outcome = SuiteOutcome.FAILED
        elif any(report.is_measured for report in reports):
            outcome = SuiteOutcome.PASSED
        else:
            outcome = SuiteOutcome.SKIPPED
        return SuiteResult(self.suite_name, outcome, metrics=metrics, message=message)

    @staticmethod
    async def run_scenarios(booking_api: BookingApi, context: SuiteContext) -> list[ScenarioReport]:
        """시나리오끼리 재고가 섞이지 않게 차례대로"""
        reports = []
        for title, scenario in (
            ("같은 좌석 경쟁", run_same_seat_scenario),
            ("자유석 수량 경쟁", run_general_stock_scenario),
            ("확정 재전송", run_resend_scenario),
        ):
            context.report_progress(f"{title} · 좌석 선택 단계 준비 → 동시 확정")
            reports.append(await scenario(booking_api))
        return reports
