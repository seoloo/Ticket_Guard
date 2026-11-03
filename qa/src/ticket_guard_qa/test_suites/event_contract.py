"""이벤트 형식 계약 시험 · docs/contracts.md 5장 · case_data/event_contracts/*.json"""
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import SuiteResult
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

EVENT_CONTRACTS_FOLDER_NAME = "event_contracts"
BROWSER_EVENTS_ENDPOINT = "events"


@dataclass(frozen=True)
class ContractCase:
    case_name: str
    description: str
    endpoint: str
    requests: list[dict[str, Any]]
    expected_status_codes: list[int]


def load_contract_cases(case_data_dir: Path) -> list[ContractCase]:
    cases = []
    for case_file in sorted((case_data_dir / EVENT_CONTRACTS_FOLDER_NAME).glob("*.json")):
        raw_case = json.loads(case_file.read_text(encoding="utf-8"))
        cases.append(ContractCase(
            case_name=case_file.stem,
            description=raw_case["description"],
            endpoint=raw_case["endpoint"],
            requests=raw_case["requests"],
            expected_status_codes=raw_case["expected_status_codes"],
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
        "{{now}}": now.isoformat(),
        "{{now_without_timezone}}": now.replace(tzinfo=None).isoformat(),
        "{{now_minus_25_hours}}": (now - timedelta(hours=25)).isoformat(),
        "{{now_plus_25_hours}}": (now + timedelta(hours=25)).isoformat(),
    }


class EventContractSuite:
    suite_name = "event_contract"
    title = "이벤트 형식 계약"
    related_codes: tuple[str, ...] = ()

    def run(self, context: SuiteContext) -> SuiteResult:
        booking_api = context.system_target.booking_api
        failed_case_names: list[str] = []
        skipped_case_names: list[str] = []

        for case in load_contract_cases(context.case_data_dir):
            if case.endpoint != BROWSER_EVENTS_ENDPOINT:
                skipped_case_names.append(case.case_name)  # TODO(예매 확정 시험 추가 시): /api/action/ 사례
                continue
            requests = fill_placeholders(case.requests, build_placeholder_values(datetime.now(timezone.utc)))
            actual_status_codes = [booking_api.submit_browser_event(request).status_code for request in requests]
            if actual_status_codes != case.expected_status_codes:
                failed_case_names.append(f"{case.case_name}({actual_status_codes})")
            context.report_progress(f"계약 사례 {case.case_name} 확인")

        message_parts = []
        if failed_case_names:
            message_parts.append("실패: " + ", ".join(failed_case_names))
        if skipped_case_names:
            message_parts.append("건너뜀: " + ", ".join(skipped_case_names))
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.FAILED if failed_case_names else SuiteOutcome.PASSED,
            metrics={"event_contract_failed_case_count": float(len(failed_case_names))},
            message=" · ".join(message_parts),
        )
