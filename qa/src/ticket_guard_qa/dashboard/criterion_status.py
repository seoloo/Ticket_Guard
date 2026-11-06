"""04 화면 합격 기준 표 · 상태 4종 · 통과 · 실패 · 대상 아님(측정 Suite 미선택) · 측정 불가(선택했지만 데이터 없음)"""
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from ticket_guard_qa.domain.enums import Comparison, SuiteOutcome
from ticket_guard_qa.domain.models import CriterionResult, RunSummary
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA, PassCriterion

DOC_REFERENCE_SEPARATOR = " · AGENTS"  # Suite 건너뜀 사유 끝의 문서 위치 · 화면에서는 생략


class CriterionStatus(StrEnum):
    PASSED = "pass"
    FAILED = "fail"
    NOT_TARGETED = "skip"
    NOT_MEASURABLE = "blocked"


STATUS_TITLES = {
    CriterionStatus.PASSED: "통과",
    CriterionStatus.FAILED: "실패",
    CriterionStatus.NOT_TARGETED: "대상 아님",
    CriterionStatus.NOT_MEASURABLE: "측정 불가",
}


@dataclass(frozen=True)
class CriterionRow:
    number: int
    criterion: PassCriterion
    result: CriterionResult
    status: CriterionStatus
    detail: str  # 측정 Suite · 실패 사유 · 미선택 Suite · 측정 불가 사유


def format_target(criterion: PassCriterion) -> str:
    """3초 이하 · 90% 이상 · 0%"""
    unit = "초" if criterion.metric_name.endswith("_sec") else "%" if criterion.metric_name.endswith("_percent") else ""
    value = f"{criterion.threshold:g}{unit}"
    if criterion.comparison is Comparison.AT_MOST:
        return value if criterion.threshold == 0 else f"{value} 이하"
    return f"{value} 이상"


def find_measuring_suite_name(summary: RunSummary, criterion: PassCriterion) -> str:
    """측정값을 실제로 낸 Suite · 없으면 기준에 정한 Suite"""
    measured_by = next((result.suite_name for result in summary.suite_results if criterion.metric_name in result.metrics), None)
    return measured_by or criterion.measuring_suite_name


def find_not_measurable_reason(summary: RunSummary, suite_name: str) -> str:
    suite_result = summary.find_suite_result(suite_name)
    if suite_result and suite_result.outcome in (SuiteOutcome.SKIPPED, SuiteOutcome.ERROR) and suite_result.message:
        return suite_result.message.splitlines()[0].split(DOC_REFERENCE_SEPARATOR)[0]
    return "측정값 없음"


def build_criterion_rows(summary: RunSummary, suite_title_by_name: dict[str, str]) -> list[CriterionRow]:
    result_by_id = {result.criterion_id: result for result in summary.criterion_results}
    rows = []
    for number, criterion in enumerate(PASS_CRITERIA, start=1):
        result = result_by_id.get(criterion.criterion_id, CriterionResult(criterion.criterion_id, None, None))
        suite_name = find_measuring_suite_name(summary, criterion)
        suite_title = suite_title_by_name.get(suite_name, suite_name)
        if result.is_passed is True:
            status, detail = CriterionStatus.PASSED, f"측정 Suite · {suite_title}"
        elif result.is_passed is False:
            status, detail = CriterionStatus.FAILED, f"목표 {format_target(criterion)} 미달"
        elif suite_name in summary.run_config.suite_names:
            status, detail = CriterionStatus.NOT_MEASURABLE, find_not_measurable_reason(summary, suite_name)
        else:
            status, detail = CriterionStatus.NOT_TARGETED, f"{suite_title} 미선택"
        rows.append(CriterionRow(number, criterion, result, status, detail))
    return rows


def count_statuses(rows: list[CriterionRow]) -> dict[CriterionStatus, int]:
    counts = Counter(row.status for row in rows)
    return {status: counts.get(status, 0) for status in CriterionStatus}
