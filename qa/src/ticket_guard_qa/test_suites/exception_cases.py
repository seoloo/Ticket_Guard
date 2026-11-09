"""예외 코드 사례 · case_data/exception_codes/*.json · E01 ~ E22 · T1 · T2 · 검증 Suite는 각 Suite의 related_codes 한 곳"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ticket_guard_qa.test_suites.suite_interface import QaSuite

EXCEPTION_CODES_FOLDER_NAME = "exception_codes"
CODE_PATTERN = re.compile(r"^([A-Z])(\d+)$")


@dataclass(frozen=True)
class ExceptionCase:
    related_code: str
    title: str
    stage: str
    input_description: str
    expected_description: str
    system_error_code: str | None  # None = 시스템 대응 기능 없음


def sort_key_for_code(code: str) -> tuple[str, int]:
    match = CODE_PATTERN.match(code)
    return (match.group(1), int(match.group(2))) if match else (code, 0)


def load_exception_cases(case_data_dir: Path) -> list[ExceptionCase]:
    cases = []
    for case_file in (case_data_dir / EXCEPTION_CODES_FOLDER_NAME).glob("*.json"):
        if case_file.name.startswith("_"):
            continue  # 작성 틀
        raw_case = json.loads(case_file.read_text(encoding="utf-8"))
        cases.append(ExceptionCase(raw_case["related_code"], raw_case["title"], raw_case["stage"],
                                   raw_case["input"], raw_case["expected"], raw_case.get("system_error_code")))
    return sorted(cases, key=lambda case: sort_key_for_code(case.related_code))


def find_covering_suites(code: str, suites: list[QaSuite]) -> list[QaSuite]:
    return [suite for suite in suites if code in suite.related_codes]
