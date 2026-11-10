"""예매 흐름 · VU 동시 접속 → 대기열 → 보안문자 → 좌석 클릭 → 확정 · 단계별 응답 시간 · 중복 판매 · 1-b ~ 1-d"""
from collections import Counter

from ticket_guard_qa.answer_key.expected_verdicts import plan_virtual_users
from ticket_guard_qa.domain.enums import BookingOutcome, SuiteOutcome
from ticket_guard_qa.domain.models import MESSAGE_LINE_SEPARATOR, SuiteResult, VirtualUserSessionResult
from ticket_guard_qa.scoring.latency_metrics import calculate_p95
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError
from ticket_guard_qa.test_suites.suite_interface import SuiteContext, SuiteGuide
from ticket_guard_qa.traffic_generators.virtual_user_traffic import (
    build_planned_user_session_plans,
    save_browser_captures,
    reset_before_traffic,
    send_virtual_user_traffic,
)

BOOKING_FLOW_SUITE_NAME = "booking_flow"
STEP_TITLES = {
    "login": "로그인", "start": "예매 시작", "queue": "대기열", "captcha": "보안문자",
    "seat_select": "좌석 클릭", "confirm": "확정",
}


def summarize_step_p95(session_results: list[VirtualUserSessionResult]) -> dict[str, float]:
    step_values: dict[str, list[float]] = {}
    for result in session_results:
        for step, latency_ms in result.step_latency_ms.items():
            step_values.setdefault(step, []).append(latency_ms)
    return {step: calculate_p95(values) for step, values in step_values.items()}


def find_double_sold_seat_ids(session_results: list[VirtualUserSessionResult]) -> list[str]:
    seat_counts = Counter(seat for result in session_results for seat in result.booked_seat_ids)
    return sorted(seat for seat, count in seat_counts.items() if count > 1)


def count_outcomes(session_results: list[VirtualUserSessionResult | None]) -> Counter:
    return Counter(result.booking_outcome for result in session_results if result and not result.is_error)


def build_message(session_results: list[VirtualUserSessionResult], planned_count: int) -> str:
    succeeded = [result for result in session_results if not result.is_error]
    outcome_counts = count_outcomes(session_results)
    parts = [
        f"예매 완료 {outcome_counts[BookingOutcome.BOOKED]} · 매진 {outcome_counts[BookingOutcome.SOLD_OUT]}"
        f" · 오류 {planned_count - len(succeeded)} / VU {planned_count}"
    ]
    if succeeded:
        parts.append(f"전체 p95 {calculate_p95([result.latency_ms for result in succeeded]):.0f}ms")
        parts.extend(f"{STEP_TITLES.get(step, step)} {value:.0f}ms" for step, value in summarize_step_p95(succeeded).items())
    fail_lines = []  # 실패 원인은 줄을 나눔 · 04 결론 · 원문 가독성
    double_sold = find_double_sold_seat_ids(session_results)
    if double_sold:
        fail_lines.append(f"FAIL: 중복 판매 {len(double_sold)}석 ({', '.join(double_sold[:5])})")
    failure_counts = Counter(result.failed_step or "unknown" for result in session_results if result.is_error)
    if failure_counts:
        fail_lines.append("FAIL: " + ", ".join(f"{step} {count}건" for step, count in failure_counts.most_common()))
    return MESSAGE_LINE_SEPARATOR.join([*fail_lines, " · ".join(parts)])


class BookingFlowSuite:
    suite_name = BOOKING_FLOW_SUITE_NAME
    title = "예매 흐름 테스트"
    related_codes: tuple[str, ...] = ("E05", "E12")
    guide = SuiteGuide(
        "많은 사람이 동시에 예매할 때 끝까지 정상 진행",
        "가상 사용자가 로그인 → 대기열 → 보안문자 → 좌석 선택 → 예매 확정 진행",
        "오류 0 · 같은 좌석 두 번 판매 0",
    )

    def run(self, context: SuiteContext) -> SuiteResult:
        run_config = context.run_config
        booking_api = context.system_target.booking_api
        planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)
        planned_count = len(planned_users)

        reset_message = reset_before_traffic(booking_api)
        context.report_progress(reset_message)
        context.report_progress(f"VU {planned_count} 동시 접속 · 오픈 전 로그인")

        def report_traffic_progress(results: list[VirtualUserSessionResult | None]) -> None:
            outcome_counts = count_outcomes(results)
            finished_count = sum(result is not None for result in results)
            context.report_progress(
                f"VU {finished_count}/{planned_count} 종료 · 예매 완료 {outcome_counts[BookingOutcome.BOOKED]}"
                f" · 매진 {outcome_counts[BookingOutcome.SOLD_OUT]}"
            )

        try:
            session_results = send_virtual_user_traffic(
                booking_api, build_planned_user_session_plans(planned_users, context.bot_profile_registry, run_config.random_seed),
                context.traffic_time_limit_sec, report_traffic_progress,
            )
            save_browser_captures(context.report_output_dir, context.run_id, planned_users, session_results)  # B3 브라우저 화면
        except AccountPoolExhaustedError as error:
            return SuiteResult(self.suite_name, SuiteOutcome.FAILED, message=f"FAIL: {error}")

        succeeded_latencies = [result.latency_ms for result in session_results if not result.is_error]
        outcome_counts = count_outcomes(session_results)
        double_sold = find_double_sold_seat_ids(session_results)
        is_passed = len(succeeded_latencies) == planned_count and not double_sold
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED if is_passed else SuiteOutcome.FAILED,
            metrics={
                "booking_flow_success_count": float(len(succeeded_latencies)),
                "booking_flow_failure_count": float(planned_count - len(succeeded_latencies)),
                "booking_flow_booked_count": float(outcome_counts[BookingOutcome.BOOKED]),
                "booking_flow_sold_out_count": float(outcome_counts[BookingOutcome.SOLD_OUT]),
                "booking_flow_double_sold_seat_count": float(len(double_sold)),
                **({"booking_flow_p95_latency_ms": calculate_p95(succeeded_latencies)} if succeeded_latencies else {}),
            },
            message=f"{build_message(session_results, planned_count)} · {reset_message}",
            details={"step_p95_latency_ms": summarize_step_p95(session_results), "double_sold_seat_ids": double_sold},
        )
