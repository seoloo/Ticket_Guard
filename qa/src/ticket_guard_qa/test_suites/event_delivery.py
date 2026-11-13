"""이벤트 전달 검증 · VU 트래픽 → 예매 사이트 → 이벤트 토픽 · 완전성 · 유일성 · 형식 · 파티션 키 · 전달 지연 · 읽기만"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from ticket_guard_qa.answer_key.expected_verdicts import plan_virtual_users
from ticket_guard_qa.domain.enums import BookingOutcome, SuiteOutcome
from ticket_guard_qa.domain.models import (
    FAIL_LINE_PREFIX,
    MESSAGE_LINE_SEPARATOR,
    REFERENCE_LINE_PREFIX,
    SuiteResult,
    VirtualUserSessionResult,
)
from ticket_guard_qa.scoring.latency_metrics import calculate_p95
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError, EventStreamReader, StreamRecord
from ticket_guard_qa.test_suites.suite_interface import SuiteContext, SuiteGuide
from ticket_guard_qa.traffic_generators.session_funnel import ACTOR_PROGRESS_DETAIL_KEY, build_funnel_progress
from ticket_guard_qa.traffic_generators.virtual_user_traffic import (
    build_planned_user_session_plans,
    reset_before_traffic,
    send_virtual_user_traffic,
)

EVENT_DELIVERY_SUITE_NAME = "event_delivery"
TEST_ACCOUNT_PREFIX = "qa-user-"
CAPTURE_SCHEMA_VERSION = 2  # 관측 이벤트 · PR #12
CAPTURE_CHUNK_EVENT_TYPE = "capture_chunk"
MAX_LISTED_ISSUE_COUNT = 10

# 예매 시도 하나에서 서버가 내야 하는 이벤트 · main web/services.py 기준
BOOKED_SERVER_EVENT_TYPES = frozenset({
    "queue_enter", "queue_register", "queue_admitted", "captcha_success", "booking_confirm_request", "booking_confirm_success",
})
SOLD_OUT_SERVER_EVENT_TYPES = frozenset({
    "queue_enter", "queue_register", "queue_admitted", "captcha_success", "booking_confirm_request", "booking_confirm_fail",
    "queue_cancel",
})
# 화면에서 원하는 좌석이 이미 전부 팔림 → 확정 없이 포기 · 확정 요청 · 실패 이벤트 없음이 정상
SOLD_OUT_BEFORE_CONFIRM_SERVER_EVENT_TYPES = SOLD_OUT_SERVER_EVENT_TYPES - {"booking_confirm_request", "booking_confirm_fail"}
REQUIRED_SERVER_EVENT_TYPES = {
    BookingOutcome.BOOKED: BOOKED_SERVER_EVENT_TYPES,
    BookingOutcome.SOLD_OUT: SOLD_OUT_SERVER_EVENT_TYPES,
}


def find_required_server_event_types(result: VirtualUserSessionResult) -> frozenset[str] | None:
    """오류 세션 = 판정 안 함 · Live 확정 소요 0 = 확정 요청을 보내지 않음"""
    if result.is_error:
        return None
    if result.booking_outcome is BookingOutcome.SOLD_OUT and result.step_latency_ms.get("confirm") == 0.0:
        return SOLD_OUT_BEFORE_CONFIRM_SERVER_EVENT_TYPES
    return REQUIRED_SERVER_EVENT_TYPES.get(result.booking_outcome)


@dataclass
class DeliveryReport:
    sent_browser_event_count: int = 0
    missing_browser_event_ids: list[str] = field(default_factory=list)  # 완전성
    duplicate_event_ids: list[str] = field(default_factory=list)  # 유일성
    missing_server_events: list[str] = field(default_factory=list)  # "예매 시도 · 이벤트 종류"
    invalid_record_count: int = 0  # 형식
    partition_violation_ids: list[str] = field(default_factory=list)  # 같은 예매 시도가 여러 파티션
    delivery_latency_ms: list[float] = field(default_factory=list)  # 적시성
    qa_record_count: int = 0
    server_event_count: int = 0
    capture_event_count: int = 0  # 스키마 v2 · 분할 메시지 포함

    @property
    def issue_count(self) -> int:
        return (len(self.missing_browser_event_ids) + len(self.duplicate_event_ids) + len(self.missing_server_events)
                + self.invalid_record_count + len(self.partition_violation_ids))


def parse_occurred_at_ms(value: object) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp() * 1000
    except ValueError:
        return None


def is_capture_event(event: dict) -> bool:
    return event.get("schemaVersion") == CAPTURE_SCHEMA_VERSION or event.get("eventType") == CAPTURE_CHUNK_EVENT_TYPE


def collect_sent_event_ids(session_results: list[VirtualUserSessionResult]) -> set[str]:
    return {event_id for result in session_results for event_id in result.sent_event_ids}


def select_qa_records(session_results: list[VirtualUserSessionResult], records: list[StreamRecord]) -> list[StreamRecord]:
    """QA 메시지 = 시험 계정 · QA가 받은 예매 시도 번호 · QA가 만든 eventId · 원본 적재 검증도 사용"""
    sent_event_ids = collect_sent_event_ids(session_results)
    attempt_ids = {result.session_key for result in session_results}
    return [
        record for record in records
        if record.event is not None and (
            str(record.event.get("userId") or "").startswith(TEST_ACCOUNT_PREFIX)
            or record.event.get("bookingAttemptId") in attempt_ids
            or record.event.get("eventId") in sent_event_ids
        )
    ]


def send_traffic_and_read_stream(
    context: SuiteContext, stream_reader: EventStreamReader,
) -> tuple[dict[int, int], list[VirtualUserSessionResult], list[StreamRecord]]:
    """초기화 → 토픽 끝 위치 기록 → VU 트래픽 → 시작 위치부터 읽기 · AccountPoolExhaustedError는 호출한 Suite가 처리"""
    run_config = context.run_config
    planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)

    context.report_progress(reset_before_traffic(context.system_target.booking_api))
    start_offsets = stream_reader.snapshot_end_offsets()
    context.report_progress(f"토픽 시작 위치 · {' · '.join(f'P{p}={o}' for p, o in sorted(start_offsets.items()))}")
    session_results = send_virtual_user_traffic(
        context.system_target.booking_api,
        build_planned_user_session_plans(planned_users, context.bot_profile_registry, run_config.random_seed, run_config.wave_size),
        context.traffic_time_limit_sec,
        lambda results: context.report_progress(f"VU {sum(r is not None for r in results)}/{len(planned_users)} 종료",
                                                actor_progress=build_funnel_progress(planned_users, results)),
        run_config.wave_size,
    )
    context.report_progress("이벤트 수신 대기 · 토픽 조회")
    return start_offsets, session_results, stream_reader.read_since(start_offsets, context.run_id)


def evaluate_delivery(session_results: list[VirtualUserSessionResult], records: list[StreamRecord]) -> DeliveryReport:
    """QA가 보낸 것(eventId · 예매 시도 번호 · 시험 계정) ↔ 토픽 메시지 대조"""
    report = DeliveryReport(invalid_record_count=sum(record.event is None for record in records))
    sent_event_ids = collect_sent_event_ids(session_results)
    report.sent_browser_event_count = len(sent_event_ids)

    qa_records = select_qa_records(session_results, records)
    report.qa_record_count = len(qa_records)
    event_id_counts = Counter(record.event.get("eventId") for record in qa_records)
    report.duplicate_event_ids = sorted(event_id for event_id, count in event_id_counts.items() if count > 1)
    report.missing_browser_event_ids = sorted(sent_event_ids - set(event_id_counts))

    server_event_types_by_attempt: dict[str, set[str]] = defaultdict(set)
    partitions_by_attempt: dict[str, set[int]] = defaultdict(set)
    for record in qa_records:
        event = record.event
        attempt_id = event.get("bookingAttemptId")
        if attempt_id:
            partitions_by_attempt[attempt_id].add(record.partition)
        if is_capture_event(event):
            report.capture_event_count += 1
            continue
        if event.get("eventType") != "seat_select":
            report.server_event_count += 1
            if attempt_id:
                server_event_types_by_attempt[attempt_id].add(event.get("eventType"))
        occurred_at_ms = parse_occurred_at_ms(event.get("occurredAt"))
        if record.timestamp_ms is not None and occurred_at_ms is not None:
            report.delivery_latency_ms.append(max(record.timestamp_ms - occurred_at_ms, 0.0))

    for result in session_results:
        required = find_required_server_event_types(result)
        if required:
            report.missing_server_events += [
                f"{result.session_key} · {event_type}"
                for event_type in sorted(required - server_event_types_by_attempt.get(result.session_key, set()))
            ]
    report.partition_violation_ids = sorted(
        attempt_id for attempt_id, partitions in partitions_by_attempt.items() if len(partitions) > 1
    )
    return report


def build_message(report: DeliveryReport, session_results: list[VirtualUserSessionResult]) -> str:
    """한 줄 = 한 항목 · FAIL 줄 먼저 · 트래픽 오류는 참고 (트래픽 안정성은 예매 흐름 · 부하 테스트 판정)"""
    failures = [
        (f"좌석 클릭 이벤트 누락 {len(report.missing_browser_event_ids)}건", report.missing_browser_event_ids),
        (f"서버 이벤트 누락 {len(report.missing_server_events)}건", report.missing_server_events),
        (f"중복 {len(report.duplicate_event_ids)}건", report.duplicate_event_ids),
        (f"파티션 키 위반 {len(report.partition_violation_ids)}건", report.partition_violation_ids),
    ]
    lines = [f"{FAIL_LINE_PREFIX}{title} · {', '.join(items[:2])}" for title, items in failures if items]
    if report.invalid_record_count:
        lines.append(f"{FAIL_LINE_PREFIX}형식 오류 메시지 {report.invalid_record_count}건")
    received_count = report.sent_browser_event_count - len(report.missing_browser_event_ids)
    lines.append(f"좌석 클릭 이벤트 {received_count}/{report.sent_browser_event_count}")
    lines.append(f"서버 이벤트 {report.server_event_count} · 누락 {len(report.missing_server_events)}"
                 f" · 중복 {len(report.duplicate_event_ids)}")
    lines.append(f"관측 이벤트 {report.capture_event_count}")
    if report.delivery_latency_ms:
        lines.append(f"전달 지연 p95 {calculate_p95(report.delivery_latency_ms):.0f}ms")
    failed_step_counts = Counter(result.failed_step or "unknown" for result in session_results if result.is_error)
    if failed_step_counts:
        lines.append(f"{REFERENCE_LINE_PREFIX}트래픽 오류 VU {sum(failed_step_counts.values())}명")
        lines += [f"{REFERENCE_LINE_PREFIX}{step} {count}건" for step, count in failed_step_counts.most_common()]
    return MESSAGE_LINE_SEPARATOR.join(lines)


class EventDeliverySuite:
    suite_name = EVENT_DELIVERY_SUITE_NAME
    title = "이벤트 전달 검증"
    related_codes: tuple[str, ...] = ()
    guide = SuiteGuide(
        "화면 · 서버 기록이 데이터 통로까지 빠짐없이 도착",
        "남긴 기록과 도착한 기록을 하나씩 대조",
        "누락 0 · 중복 0",
    )

    def run(self, context: SuiteContext) -> SuiteResult:
        stream_reader = context.system_target.event_stream_reader
        if stream_reader is None:
            raise NotImplementedError("이벤트 스트림 읽기 미설정 · TICKET_GUARD_QA_KAFKA_BOOTSTRAP_SERVERS")
        try:
            start_offsets, session_results, records = send_traffic_and_read_stream(context, stream_reader)
        except AccountPoolExhaustedError as error:
            return SuiteResult(self.suite_name, SuiteOutcome.FAILED, message=f"FAIL: {error}")

        report = evaluate_delivery(session_results, records)
        is_passed = report.issue_count == 0  # 전달 결과만 판정
        run_config = context.run_config
        planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED if is_passed else SuiteOutcome.FAILED,
            metrics={
                "event_delivery_missing_count": float(len(report.missing_browser_event_ids) + len(report.missing_server_events)),
                "event_delivery_duplicate_count": float(len(report.duplicate_event_ids)),
                "event_delivery_invalid_count": float(report.invalid_record_count),
                "event_delivery_partition_violation_count": float(len(report.partition_violation_ids)),
                "event_delivery_qa_record_count": float(report.qa_record_count),
                **({"event_delivery_latency_p95_ms": calculate_p95(report.delivery_latency_ms)} if report.delivery_latency_ms else {}),
            },
            message=build_message(report, session_results),
            details={
                "start_offsets": {str(partition): offset for partition, offset in start_offsets.items()},
                "read_record_count": len(records),
                ACTOR_PROGRESS_DETAIL_KEY: build_funnel_progress(planned_users, session_results),
                "missing_browser_event_ids": report.missing_browser_event_ids[:MAX_LISTED_ISSUE_COUNT],
                "missing_server_events": report.missing_server_events[:MAX_LISTED_ISSUE_COUNT],
                "duplicate_event_ids": report.duplicate_event_ids[:MAX_LISTED_ISSUE_COUNT],
                "partition_violation_ids": report.partition_violation_ids[:MAX_LISTED_ISSUE_COUNT],
            },
        )
