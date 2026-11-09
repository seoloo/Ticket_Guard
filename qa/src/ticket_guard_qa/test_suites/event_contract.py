"""이벤트 형식 계약 시험 · docs/contracts.md 5장 · case_data/event_contracts/*.json"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import SuiteResult
from ticket_guard_qa.system_targets.target_interfaces import (
    AccountPoolExhaustedError,
    BookingApi,
    ConfirmResponse,
    PipelineReader,
    StoredOutcome,
)
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

EVENT_CONTRACTS_FOLDER_NAME = "event_contracts"
BROWSER_EVENTS_ENDPOINT = "events"
QUARANTINE_REASON_CODES = ("PARSE_ERROR", "MISSING_FIELD", "INVALID_FORMAT", "UNSUPPORTED_SCHEMA", "DUPLICATE_EVENT_ID")  # docs/contracts.md 3-4 · QA 제안
KAFKA_ENDPOINT = "kafka"  # Django를 거치지 않는 토픽 메시지 · 시스템 파이프라인 입력 형식 시험
ACTION_ENDPOINT = "action"  # /api/action/ 예매 확정 · 좌석 선택 단계 VU 하나
ACTION_SHOW_ID = "blue-hour"  # 지정석
CLEAN_COLLECTION_NAME = "clean_events"
STORAGE_WAIT_SEC = 30.0  # Spark 처리 주기 · 재시도 여유
STORAGE_POLL_INTERVAL_SEC = 1.0
ACCEPTED_STATUS_TOKEN = "accepted"
ACCEPTED_STATUS_CODES = (200, 202)  # 200 전달 완료 · 202 전달 대기 · Kafka 상태에 따라 달라짐
KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class ExpectedStorage:
    """파이프라인 처리 뒤 기대 결과 · docs/contracts.md 5-1"""
    activity_event_count: int | None  # None = 아직 정하지 않음
    quarantine_reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ContractCase:
    case_name: str
    description: str
    endpoint: str
    requests: list[dict[str, Any]]
    expected_status_codes: list[int | str]  # 숫자 또는 "accepted"
    kafka_messages: list[dict[str, Any]]
    expected_storage: ExpectedStorage | None


def load_contract_cases(case_data_dir: Path) -> list[ContractCase]:
    cases = []
    for case_file in sorted((case_data_dir / EVENT_CONTRACTS_FOLDER_NAME).glob("*.json")):
        raw_case = json.loads(case_file.read_text(encoding="utf-8"))
        raw_storage = raw_case.get("expected_storage")
        cases.append(ContractCase(
            case_name=case_file.stem,
            description=raw_case["description"],
            endpoint=raw_case["endpoint"],
            requests=raw_case.get("requests", []),
            expected_status_codes=raw_case.get("expected_status_codes", []),
            kafka_messages=raw_case.get("kafka_messages", []),
            expected_storage=ExpectedStorage(
                raw_storage["activity_event_count"], tuple(raw_storage["quarantine_reason_codes"])
            ) if raw_storage else None,
        ))
    return cases


def fill_placeholders(value: Any, replacements: dict[str, str]) -> Any:
    """{{event_id}} · {{now}} 등 → 실행 시점 값 · 같은 사례 안에서는 같은 eventId"""
    if isinstance(value, dict):
        return {key: fill_placeholders(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [fill_placeholders(item, replacements) for item in value]
    if isinstance(value, str) and value in replacements:
        return replacements[value]
    return value


def build_placeholder_values(now: datetime) -> dict[str, str]:
    return {
        "{{event_id}}": str(uuid.uuid4()),
        "{{page_view_id}}": str(uuid.uuid4()),
        "{{now}}": now.isoformat(),
        "{{now_kst}}": now.astimezone(KST).isoformat(),
        "{{now_without_timezone}}": now.replace(tzinfo=None).isoformat(),
        "{{now_minus_25_hours}}": (now - timedelta(hours=25)).isoformat(),
        "{{now_plus_25_hours}}": (now + timedelta(hours=25)).isoformat(),
    }


def is_expected_status(actual_status_code: int, expected: int | str) -> bool:
    if expected == ACCEPTED_STATUS_TOKEN:
        return actual_status_code in ACCEPTED_STATUS_CODES
    return actual_status_code == expected


def encode_message_value(value: Any) -> bytes:
    """객체 = JSON · 문자열 = 그대로 (형식 오류 사례)"""
    return value.encode() if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode()


async def send_action_requests(booking_api: BookingApi, requests: list[dict[str, Any]]) -> list[ConfirmResponse]:
    contender = await booking_api.prepare_seat_contender(ACTION_SHOW_ID)
    try:
        return [
            await booking_api.send_confirm_with_last_sequence(
                contender, tuple(request["seat_ids"]), request["quantity"], request["is_same_sequence"])
            for request in requests
        ]
    finally:
        await booking_api.release_seat_contender(contender)


def wait_for_stored_outcomes(
    pipeline_reader: PipelineReader, positions: list[tuple[int, int]], wait_sec: float, poll_interval_sec: float,
) -> list[StoredOutcome]:
    deadline = time.monotonic() + wait_sec
    while True:
        outcomes = pipeline_reader.read_stored_outcomes(positions)
        if len(outcomes) >= len(positions) or time.monotonic() >= deadline:
            return outcomes
        time.sleep(poll_interval_sec)


def matches_expected_statuses(actual_status_codes: list[int], expected_status_codes: list[int | str]) -> bool:
    return len(actual_status_codes) == len(expected_status_codes) and all(
        is_expected_status(actual, expected) for actual, expected in zip(actual_status_codes, expected_status_codes)
    )


class EventContractSuite:
    suite_name = "event_contract"
    title = "이벤트 계약 테스트"
    related_codes: tuple[str, ...] = ("E20",)  # 오래된 순번 재전송

    def __init__(self, storage_wait_sec: float = STORAGE_WAIT_SEC, poll_interval_sec: float = STORAGE_POLL_INTERVAL_SEC) -> None:
        self.storage_wait_sec = storage_wait_sec
        self.poll_interval_sec = poll_interval_sec

    def check_case(self, context: SuiteContext, case: ContractCase) -> str | None:
        """실패 이유 · None = 통과 · 대상 미설정은 NotImplementedError"""
        booking_api = context.system_target.booking_api
        if case.endpoint == BROWSER_EVENTS_ENDPOINT:
            requests = fill_placeholders(case.requests, build_placeholder_values(datetime.now(timezone.utc)))
            actual_status_codes = [booking_api.submit_browser_event(request).status_code for request in requests]
            return None if matches_expected_statuses(actual_status_codes, case.expected_status_codes) else str(actual_status_codes)
        if case.endpoint == ACTION_ENDPOINT:
            responses = asyncio.run(send_action_requests(booking_api, case.requests))
            actual = [(response.status_code, response.error_code) for response in responses]
            expected = [(status, request["expected_error_code"]) for status, request in zip(case.expected_status_codes, case.requests)]
            return None if actual == expected else str(actual)
        if case.endpoint == KAFKA_ENDPOINT:
            return self.check_kafka_case(context, case)
        raise NotImplementedError(f"모르는 endpoint {case.endpoint}")

    def check_kafka_case(self, context: SuiteContext, case: ContractCase) -> str | None:
        """토픽 주입 → 정제 · 격리 저장 결과 대조 · docs/contracts.md 5-1"""
        injector = context.system_target.event_injector
        if injector is None:
            raise NotImplementedError("토픽 주입 미설정")
        messages = fill_placeholders(case.kafka_messages, build_placeholder_values(datetime.now(timezone.utc)))
        positions = injector.inject_messages([(message.get("key"), encode_message_value(message["value"])) for message in messages])
        outcomes = wait_for_stored_outcomes(context.system_target.pipeline_reader, positions, self.storage_wait_sec, self.poll_interval_sec)
        clean_count = sum(outcome.collection_name == CLEAN_COLLECTION_NAME for outcome in outcomes)
        reason_codes = sorted(outcome.reason_code or "" for outcome in outcomes if outcome.collection_name != CLEAN_COLLECTION_NAME)
        expected = case.expected_storage
        is_matched = (len(outcomes) >= len(positions) and sorted(expected.quarantine_reason_codes) == reason_codes
                      and (expected.activity_event_count is None or expected.activity_event_count == clean_count))
        return None if is_matched else f"정제 {clean_count} · 격리 {reason_codes or '없음'} · 저장 {len(outcomes)}/{len(positions)}"

    def run(self, context: SuiteContext) -> SuiteResult:
        failed_case_names: list[str] = []
        skipped_case_names: list[str] = []

        for case in load_contract_cases(context.case_data_dir):
            context.report_progress(f"계약 케이스 {case.case_name} 검증")
            try:
                failure = self.check_case(context, case)
            except (NotImplementedError, AccountPoolExhaustedError) as error:
                skipped_case_names.append(f"{case.case_name}({error})")
                continue
            if failure:
                failed_case_names.append(f"{case.case_name}({failure})")

        message_parts = []
        if failed_case_names:
            message_parts.append("FAIL: " + ", ".join(failed_case_names))
        if skipped_case_names:
            message_parts.append("SKIP: " + ", ".join(skipped_case_names))
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.FAILED if failed_case_names else SuiteOutcome.PASSED,
            metrics={"event_contract_failed_case_count": float(len(failed_case_names))},
            message=" · ".join(message_parts),
        )
