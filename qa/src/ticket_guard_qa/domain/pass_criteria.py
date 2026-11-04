"""합격 기준 7개 · 기획서 21쪽 · 변경은 관리자 승인"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import Comparison
from ticket_guard_qa.domain.models import CriterionResult


@dataclass(frozen=True)
class PassCriterion:
    criterion_id: str
    title: str
    metric_name: str
    threshold: float
    comparison: Comparison

    def is_met_by(self, measured_value: float) -> bool:
        if self.comparison is Comparison.AT_MOST:
            return measured_value <= self.threshold
        return measured_value >= self.threshold


PASS_CRITERIA: tuple[PassCriterion, ...] = (
    PassCriterion("api_latency", "판정 API p95", "api_latency_p95_sec", 3.0, Comparison.AT_MOST),
    PassCriterion("api_error_rate", "판정 API 오류율", "api_error_rate_percent", 0.0, Comparison.AT_MOST),
    PassCriterion("gold_latency", "Gold 반영 p95", "gold_latency_p95_sec", 10.0, Comparison.AT_MOST),
    PassCriterion("recovery_time", "장애 복구 시간", "recovery_time_sec", 60.0, Comparison.AT_MOST),
    PassCriterion("bot_abd_detection", "봇 A · B · D 탐지율", "bot_abd_detection_rate_percent", 90.0, Comparison.AT_LEAST),
    PassCriterion("bot_c_detection", "봇 C 탐지율", "bot_c_detection_rate_percent", 70.0, Comparison.AT_LEAST),
    PassCriterion("human_false_positive", "사람 오탐률", "human_false_positive_rate_percent", 1.0, Comparison.AT_MOST),
)

PASS_CRITERION_BY_ID = {criterion.criterion_id: criterion for criterion in PASS_CRITERIA}


def evaluate_pass_criteria(metrics: dict[str, float]) -> list[CriterionResult]:
    results = []
    for criterion in PASS_CRITERIA:
        measured_value = metrics.get(criterion.metric_name)
        is_passed = None if measured_value is None else criterion.is_met_by(measured_value)
        results.append(CriterionResult(criterion.criterion_id, measured_value, is_passed))
    return results
