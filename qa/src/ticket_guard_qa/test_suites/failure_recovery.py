"""장애 복구 · 정제 · 격리 저장 작업 중지 → 이벤트 전송 → 재시작 → 전부 저장될 때까지(RTO) · 누락 · 중복 0"""
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone

from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, SuiteResult
from ticket_guard_qa.system_targets.target_interfaces import PIPELINE_SERVICE_NAME, BookingApi, PipelineReader
from ticket_guard_qa.test_suites.event_contract import build_placeholder_values, fill_placeholders, load_contract_cases
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

EVENT_TEMPLATE_CASE_NAME = "valid_browser_event"
EVENT_COUNT_PER_PHASE = 20  # 중지 전 · 중지 중 각각
PROCESS_WAIT_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 1.0
RECOVERY_TIME_LIMIT_SEC = 60.0  # 합격 기준 장애 복구 시간
MAX_LISTED_EVENT_COUNT = 3


def build_events(template: dict, count: int) -> list[dict]:
    return [fill_placeholders(template, build_placeholder_values(datetime.now(timezone.utc))) for _ in range(count)]


def send_events(booking_api: BookingApi, events: list[dict]) -> list[str]:
    """받아들인 이벤트의 eventId만"""
    return [event["eventId"] for event in events if booking_api.submit_browser_event(event).status_code in (200, 202)]


def wait_until_processed(
    pipeline_reader: PipelineReader, event_ids: list[str], timeout_sec: float, poll_interval_sec: float,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[str], float]:
    """전부 저장될 때까지 · (저장된 eventId 목록, 걸린 초)"""
    started_at = time.monotonic()
    while True:
        processed_event_ids = pipeline_reader.find_processed_event_ids(event_ids)
        elapsed_sec = time.monotonic() - started_at
        if set(event_ids) <= set(processed_event_ids) or elapsed_sec >= timeout_sec:
            return processed_event_ids, elapsed_sec
        sleep(poll_interval_sec)


class FailureRecoverySuite:
    suite_name = "failure_recovery"
    title = "장애 복구 테스트"
    related_codes: tuple[str, ...] = ()

    def __init__(self, timeout_sec: float = PROCESS_WAIT_TIMEOUT_SEC, poll_interval_sec: float = POLL_INTERVAL_SEC) -> None:
        self.timeout_sec = timeout_sec
        self.poll_interval_sec = poll_interval_sec

    def run(self, context: SuiteContext) -> SuiteResult:
        booking_api = context.system_target.booking_api
        pipeline_reader = context.system_target.pipeline_reader
        process_control = context.system_target.process_control
        template = next(case.requests[0] for case in load_contract_cases(context.case_data_dir)
                        if case.case_name == EVENT_TEMPLATE_CASE_NAME)

        context.report_progress(f"중지 전 이벤트 {EVENT_COUNT_PER_PHASE}건 · 정상 저장 확인")
        before_event_ids = send_events(booking_api, build_events(template, EVENT_COUNT_PER_PHASE))
        processed_before, _ = wait_until_processed(pipeline_reader, before_event_ids, self.timeout_sec, self.poll_interval_sec)
        if not before_event_ids or not set(before_event_ids) <= set(processed_before):
            return SuiteResult(self.suite_name, SuiteOutcome.FAILED, message=(
                f"{FAIL_LINE_PREFIX}중지 전 정상 저장 확인 실패 · 저장 {len(set(processed_before))}/{len(before_event_ids)}"))

        context.report_progress("정제 · 격리 저장 작업 중지")
        process_control.stop_service(PIPELINE_SERVICE_NAME)
        try:
            context.report_progress(f"중지 중 이벤트 {EVENT_COUNT_PER_PHASE}건")
            outage_event_ids = send_events(booking_api, build_events(template, EVENT_COUNT_PER_PHASE))
        finally:
            context.report_progress("정제 · 격리 저장 작업 재시작 · 복구 시간 측정")
            process_control.start_service(PIPELINE_SERVICE_NAME)

        all_event_ids = before_event_ids + outage_event_ids
        processed_event_ids, elapsed_sec = wait_until_processed(pipeline_reader, all_event_ids, self.timeout_sec, self.poll_interval_sec)
        counts = Counter(processed_event_ids)
        missing_event_ids = [event_id for event_id in all_event_ids if event_id not in counts]
        duplicate_event_ids = [event_id for event_id in all_event_ids if counts[event_id] > 1]
        is_recovered = not missing_event_ids
        is_passed = is_recovered and not duplicate_event_ids and elapsed_sec <= RECOVERY_TIME_LIMIT_SEC

        lines = []
        if missing_event_ids:
            lines.append(f"{FAIL_LINE_PREFIX}재시작 후 누락 {len(missing_event_ids)}건 · {', '.join(missing_event_ids[:MAX_LISTED_EVENT_COUNT])}")
        if duplicate_event_ids:
            lines.append(f"{FAIL_LINE_PREFIX}재시작 후 중복 저장 {len(duplicate_event_ids)}건 · checkpoint 이후 재처리")
        if is_recovered and elapsed_sec > RECOVERY_TIME_LIMIT_SEC:
            lines.append(f"{FAIL_LINE_PREFIX}복구 시간 {elapsed_sec:.1f}초 · 기준 {RECOVERY_TIME_LIMIT_SEC:.0f}초 초과")
        lines.append(f"복구 시간 {elapsed_sec:.1f}초" if is_recovered else f"복구 미완료 · {self.timeout_sec:.0f}초 대기")
        lines.append(f"저장 {len(set(processed_event_ids))}/{len(all_event_ids)} · 중지 중 이벤트 {len(outage_event_ids)}건")
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED if is_passed else SuiteOutcome.FAILED,
            metrics={
                **({"recovery_time_sec": elapsed_sec} if is_recovered else {}),
                "failure_recovery_missing_count": float(len(missing_event_ids)),
                "failure_recovery_duplicate_count": float(len(duplicate_event_ids)),
            },
            message=MESSAGE_LINE_SEPARATOR.join(lines),
            details={"sent_event_count": len(all_event_ids), "outage_event_count": len(outage_event_ids)},
        )
