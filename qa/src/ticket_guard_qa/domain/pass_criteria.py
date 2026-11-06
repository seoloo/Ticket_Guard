"""합격 기준 7개 · 기획서 21쪽 · 변경은 관리자 승인"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import Comparison
from ticket_guard_qa.domain.models import CriterionResult


@dataclass(frozen=True)
class PassCriterion:
    criterion_id: str
    title: str  # 기술 용어 · 현업 표기
    metric_name: str
    threshold: float
    comparison: Comparison
    display_name: str = ""  # 쉬운 이름 · 처음 보는 관리자용 · 04 화면
    meaning: str = ""  # 한 줄 정의 · 04 화면 의미 열
    measuring_suite_name: str = ""  # 이 기준을 재는 Suite · 미선택 = 대상 아님

    def is_met_by(self, measured_value: float) -> bool:
        if self.comparison is Comparison.AT_MOST:
            return measured_value <= self.threshold
        return measured_value >= self.threshold


VERDICT_ACCURACY = "verdict_accuracy"
PASS_CRITERIA: tuple[PassCriterion, ...] = (
    PassCriterion("api_latency", "판정 API p95 지연", "api_latency_p95_sec", 3.0, Comparison.AT_MOST,
                  "판정 응답 시간", "판정 요청 100건 중 95건이 이 시간 안에 응답", VERDICT_ACCURACY),
    PassCriterion("api_error_rate", "판정 API 오류율", "api_error_rate_percent", 0.0, Comparison.AT_MOST,
                  "판정 실패율", "판정 요청 중 오류 응답 비율", VERDICT_ACCURACY),
    PassCriterion("gold_latency", "Gold 반영 p95 지연", "gold_latency_p95_sec", 10.0, Comparison.AT_MOST,
                  "집계 반영 시간", "클릭 발생 → 집계 결과 반영까지 · 100건 중 95건 기준", "pipeline_latency"),
    PassCriterion("recovery_time", "장애 복구 시간(RTO)", "recovery_time_sec", 60.0, Comparison.AT_MOST,
                  "장애 복구 시간", "구성 요소 중단 → 정상 처리 재개까지", "failure_recovery"),
    PassCriterion("bot_abd_detection", "봇 A · B · D 탐지율", "bot_abd_detection_rate_percent", 90.0, Comparison.AT_LEAST,
                  "매크로 탐지율", "고속 반복 · 위장 · 세션 복제 매크로 중 추가 확인 이상 판정 비율", VERDICT_ACCURACY),
    PassCriterion("bot_c_detection", "봇 C 탐지율", "bot_c_detection_rate_percent", 70.0, Comparison.AT_LEAST,
                  "브라우저 자동화 탐지율", "브라우저 자동화 매크로 중 추가 확인 이상 판정 비율", VERDICT_ACCURACY),
    PassCriterion("human_false_positive", "오탐률(FPR)", "human_false_positive_rate_percent", 1.0, Comparison.AT_MOST,
                  "정상 사용자 오탐률", "정상 사용자 중 추가 확인 이상으로 잘못 판정된 비율", VERDICT_ACCURACY),
)

PASS_CRITERION_BY_ID = {criterion.criterion_id: criterion for criterion in PASS_CRITERIA}


def evaluate_pass_criteria(metrics: dict[str, float]) -> list[CriterionResult]:
    results = []
    for criterion in PASS_CRITERIA:
        measured_value = metrics.get(criterion.metric_name)
        is_passed = None if measured_value is None else criterion.is_met_by(measured_value)
        results.append(CriterionResult(criterion.criterion_id, measured_value, is_passed))
    return results
