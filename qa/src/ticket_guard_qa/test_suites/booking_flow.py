"""예매 흐름 · VU가 로그인 → 대기열 → 보안문자 → 좌석 선택 단계까지 가는지 · 단계별 응답 시간 · 1-b · 1-d"""
from collections import Counter

from ticket_guard_qa.domain.enums import ActorType, SuiteOutcome
from ticket_guard_qa.domain.models import SuiteResult, VirtualUserSessionResult
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE
from ticket_guard_qa.scoring.latency_metrics import calculate_p95
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

BOOKING_FLOW_SUITE_NAME = "booking_flow"
PROGRESS_REPORT_EVERY = 10
STEP_TITLES = {"login": "로그인", "start": "예매 시작", "queue": "대기열", "captcha": "보안문자"}


def summarize_step_p95(session_results: list[VirtualUserSessionResult]) -> dict[str, float]:
    step_values: dict[str, list[float]] = {}
    for result in session_results:
        for step, latency_ms in result.step_latency_ms.items():
            step_values.setdefault(step, []).append(latency_ms)
    return {step: calculate_p95(values) for step, values in step_values.items()}


def build_message(session_results: list[VirtualUserSessionResult], planned_count: int) -> str:
    succeeded = [result for result in session_results if not result.is_error]
    parts = [f"좌석 선택 단계 도착 {len(succeeded)}/{planned_count}"]
    if succeeded:
        parts.append(f"전체 p95 {calculate_p95([result.latency_ms for result in succeeded]):.0f}ms")
        parts.extend(f"{STEP_TITLES.get(step, step)} {value:.0f}ms" for step, value in summarize_step_p95(succeeded).items())
    failure_counts = Counter(result.failed_step or "unknown" for result in session_results if result.is_error)
    if failure_counts:
        parts.insert(0, "FAIL: " + ", ".join(f"{step} {count}건" for step, count in failure_counts.most_common()))
    return " · ".join(parts)


class BookingFlowSuite:
    suite_name = BOOKING_FLOW_SUITE_NAME
    title = "예매 흐름 테스트"
    related_codes: tuple[str, ...] = ("T1",)  # 대기열

    def run(self, context: SuiteContext) -> SuiteResult:
        booking_api = context.system_target.booking_api
        planned_count = context.run_config.virtual_user_count
        behavior = DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN]  # 행동 값 적용은 1-c
        session_results: list[VirtualUserSessionResult] = []
        shortage_message = ""

        for index in range(planned_count):
            try:
                session_results.append(booking_api.start_virtual_user_session(behavior))
            except AccountPoolExhaustedError as error:
                shortage_message = str(error)
                break
            finished_count = index + 1
            if finished_count % PROGRESS_REPORT_EVERY == 0 or finished_count == planned_count:
                succeeded_count = sum(not result.is_error for result in session_results)
                context.report_progress(f"VU {finished_count}/{planned_count} · 좌석 선택 단계 도착 {succeeded_count}")

        failed_count = sum(result.is_error for result in session_results)
        succeeded_latencies = [result.latency_ms for result in session_results if not result.is_error]
        message = build_message(session_results, planned_count)
        if shortage_message:
            message = f"FAIL: {shortage_message} · {message}"
        is_passed = not shortage_message and failed_count == 0
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED if is_passed else SuiteOutcome.FAILED,
            metrics={
                "booking_flow_success_count": float(len(succeeded_latencies)),
                "booking_flow_failure_count": float(planned_count - len(succeeded_latencies)),
                **({"booking_flow_p95_latency_ms": calculate_p95(succeeded_latencies)} if succeeded_latencies else {}),
            },
            message=message,
            details={"step_p95_latency_ms": summarize_step_p95(session_results)},
        )
