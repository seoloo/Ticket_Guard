"""원본 적재 검증 · 이벤트 토픽 QA 메시지 ↔ 원본 DB(ticketguard_raw) · 위치(파티션 · 오프셋)로 대조 · 완전성 · 유일성 · 분류 · 원문 보존 · 적재 지연 · 읽기만"""
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, SuiteResult
from ticket_guard_qa.domain.raw_event_routing import UNCLASSIFIED_COLLECTION_NAME, find_expected_raw_collection
from ticket_guard_qa.scoring.latency_metrics import calculate_p95
from ticket_guard_qa.system_targets.target_interfaces import (
    AccountPoolExhaustedError,
    RawEventReader,
    RawStoredRecord,
    StreamRecord,
)
from ticket_guard_qa.test_suites.event_delivery import select_qa_records, send_traffic_and_read_stream
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

RAW_INGEST_SUITE_NAME = "raw_ingest"
RAW_INGEST_WAIT_SEC = 30.0  # 원본 적재 배치 1초 · 재시도 여유
RAW_INGEST_POLL_INTERVAL_SEC = 1.0
MAX_LISTED_ISSUE_COUNT = 10

Position = tuple[int, int]  # (파티션, 오프셋)


def format_position(position: Position) -> str:
    return f"P{position[0]}:{position[1]}"


@dataclass
class RawIngestReport:
    qa_record_count: int = 0
    stored_record_count: int = 0
    missing_positions: list[str] = field(default_factory=list)  # 완전성
    duplicate_positions: list[str] = field(default_factory=list)  # 유일성 · 같은 위치 2건 이상
    misrouted_positions: list[str] = field(default_factory=list)  # 분류 정확성 · "위치 · eventType → 실제 컬렉션"
    unclassified_positions: list[str] = field(default_factory=list)  # 분류 정확성 · 미분류로 감
    altered_positions: list[str] = field(default_factory=list)  # 원문 보존
    ingest_latency_ms: list[float] = field(default_factory=list)  # 적재 지연 · ingestedAt − timestampMs

    @property
    def issue_count(self) -> int:
        return (len(self.missing_positions) + len(self.duplicate_positions) + len(self.misrouted_positions)
                + len(self.unclassified_positions) + len(self.altered_positions))


def evaluate_raw_ingest(qa_records: list[StreamRecord], stored_records: list[RawStoredRecord]) -> RawIngestReport:
    report = RawIngestReport(qa_record_count=len(qa_records))
    stored_by_position: dict[Position, list[RawStoredRecord]] = defaultdict(list)
    for stored_record in stored_records:
        stored_by_position[(stored_record.partition, stored_record.offset)].append(stored_record)

    for record in sorted(qa_records, key=lambda item: (item.partition, item.offset)):
        position = (record.partition, record.offset)
        label = format_position(position)
        matches = stored_by_position.get(position, [])
        if not matches:
            report.missing_positions.append(label)
            continue
        report.stored_record_count += 1
        if len(matches) > 1:
            report.duplicate_positions.append(f"{label} · {len(matches)}건")
        stored_record = matches[0]
        expected_collection = find_expected_raw_collection(record.event)
        if stored_record.collection_name != expected_collection:
            event_type = record.event.get("eventType") if record.event else None
            issue = f"{label} · {event_type} → {stored_record.collection_name}"
            if stored_record.collection_name == UNCLASSIFIED_COLLECTION_NAME:
                report.unclassified_positions.append(f"{issue} ({stored_record.routing_reason or '사유 없음'})")
            else:
                report.misrouted_positions.append(issue)
        if stored_record.event != record.event:
            report.altered_positions.append(label)
        timestamp_ms = stored_record.timestamp_ms if stored_record.timestamp_ms is not None else record.timestamp_ms
        if stored_record.ingested_at_ms is not None and timestamp_ms is not None:
            report.ingest_latency_ms.append(max(stored_record.ingested_at_ms - timestamp_ms, 0.0))
    return report


def read_stored_records(
    raw_event_reader: RawEventReader, positions: list[Position], wait_sec: float, poll_interval_sec: float,
    sleep: Callable[[float], None] = time.sleep,
) -> list[RawStoredRecord]:
    """전부 보일 때까지 다시 조회 · 최대 wait_sec · 마지막에 전체 한 번 더 (늦게 생긴 중복 포함)"""
    remaining_positions = set(positions)
    deadline = time.monotonic() + wait_sec
    while remaining_positions:
        found_positions = {(record.partition, record.offset)
                           for record in raw_event_reader.find_by_positions(sorted(remaining_positions))}
        remaining_positions -= found_positions
        if not remaining_positions or time.monotonic() >= deadline:
            break
        sleep(poll_interval_sec)
    return raw_event_reader.find_by_positions(positions)


def build_message(report: RawIngestReport) -> str:
    """한 줄 = 한 항목 · FAIL 줄 먼저"""
    failures = [
        (f"적재 누락 {len(report.missing_positions)}건", report.missing_positions),
        (f"중복 적재 {len(report.duplicate_positions)}건", report.duplicate_positions),
        (f"오분류 {len(report.misrouted_positions)}건", report.misrouted_positions),
        (f"미분류 {len(report.unclassified_positions)}건", report.unclassified_positions),
        (f"원문 변형 {len(report.altered_positions)}건", report.altered_positions),
    ]
    lines = [f"{FAIL_LINE_PREFIX}{title} · {', '.join(items[:2])}" for title, items in failures if items]
    lines.append(f"원본 적재 {report.stored_record_count}/{report.qa_record_count}")
    lines.append(f"중복 {len(report.duplicate_positions)} · 오분류 {len(report.misrouted_positions)}"
                 f" · 미분류 {len(report.unclassified_positions)} · 원문 변형 {len(report.altered_positions)}")
    if report.ingest_latency_ms:
        lines.append(f"적재 지연 p95 {calculate_p95(report.ingest_latency_ms):.0f}ms")
    return MESSAGE_LINE_SEPARATOR.join(lines)


class RawIngestSuite:
    suite_name = RAW_INGEST_SUITE_NAME
    title = "원본 적재 검증"
    related_codes: tuple[str, ...] = ()

    def __init__(self, wait_sec: float = RAW_INGEST_WAIT_SEC, poll_interval_sec: float = RAW_INGEST_POLL_INTERVAL_SEC) -> None:
        self.wait_sec = wait_sec
        self.poll_interval_sec = poll_interval_sec

    def run(self, context: SuiteContext) -> SuiteResult:
        stream_reader = context.system_target.event_stream_reader
        raw_event_reader = context.system_target.raw_event_reader
        if stream_reader is None:
            raise NotImplementedError("이벤트 스트림 읽기 미설정 · TICKET_GUARD_QA_KAFKA_BOOTSTRAP_SERVERS")
        if raw_event_reader is None:
            raise NotImplementedError("원본 DB 읽기 미설정 · TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI · 읽기 전용 계정")
        try:
            _, session_results, records = send_traffic_and_read_stream(context, stream_reader)
        except AccountPoolExhaustedError as error:
            return SuiteResult(self.suite_name, SuiteOutcome.FAILED, message=f"FAIL: {error}")

        qa_records = select_qa_records(session_results, records)
        context.report_progress(f"원본 DB 조회 · QA 메시지 {len(qa_records)}건 · 최대 {self.wait_sec:.0f}초 대기")
        positions = [(record.partition, record.offset) for record in qa_records]
        stored_records = read_stored_records(raw_event_reader, positions, self.wait_sec, self.poll_interval_sec) if positions else []
        report = evaluate_raw_ingest(qa_records, stored_records)
        is_passed = report.qa_record_count > 0 and report.issue_count == 0
        message = build_message(report) if report.qa_record_count else f"{FAIL_LINE_PREFIX}토픽에서 QA 메시지 0건 · 이벤트 전달 검증 먼저 확인"
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED if is_passed else SuiteOutcome.FAILED,
            metrics={
                "raw_ingest_qa_record_count": float(report.qa_record_count),
                "raw_ingest_missing_count": float(len(report.missing_positions)),
                "raw_ingest_duplicate_count": float(len(report.duplicate_positions)),
                "raw_ingest_misrouted_count": float(len(report.misrouted_positions) + len(report.unclassified_positions)),
                "raw_ingest_altered_count": float(len(report.altered_positions)),
                **({"raw_ingest_latency_p95_ms": calculate_p95(report.ingest_latency_ms)} if report.ingest_latency_ms else {}),
            },
            message=message,
            details={
                "read_record_count": len(records),
                "stored_record_count": report.stored_record_count,
                "missing_positions": report.missing_positions[:MAX_LISTED_ISSUE_COUNT],
                "duplicate_positions": report.duplicate_positions[:MAX_LISTED_ISSUE_COUNT],
                "misrouted_positions": report.misrouted_positions[:MAX_LISTED_ISSUE_COUNT],
                "unclassified_positions": report.unclassified_positions[:MAX_LISTED_ISSUE_COUNT],
                "altered_positions": report.altered_positions[:MAX_LISTED_ISSUE_COUNT],
            },
        )
