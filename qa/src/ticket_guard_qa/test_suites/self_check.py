"""QA 자기 검사 · 정답을 아는 고정 응답 14개로 점수 계산이 맞는지 · 틀리는 대상을 실패로 잡는지"""
import math

from ticket_guard_qa.domain.enums import ActorType, SuiteOutcome, VerdictStage
from ticket_guard_qa.domain.models import AnswerKey, SessionKey, SuiteResult, SystemVerdicts
from ticket_guard_qa.scoring.confusion_matrix import build_confusion_matrix
from ticket_guard_qa.scoring.detection_metrics import calculate_detection_metrics
from ticket_guard_qa.scoring.latency_metrics import calculate_p95
from ticket_guard_qa.system_targets.fake_system import (
    AlwaysWrongVerdictReader,
    FakePipelineReader,
    FakeVerdictReader,
)
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

# fake_system.FIXED_SESSION_VERDICTS의 정답 · 사람 6 · 봇 A · B · C · D 각 2
FIXED_ANSWER_KEY: AnswerKey = {
    **{SessionKey(f"fake-{number:02d}"): ActorType.HUMAN for number in range(1, 7)},
    SessionKey("fake-07"): ActorType.BOT_A, SessionKey("fake-08"): ActorType.BOT_A,
    SessionKey("fake-09"): ActorType.BOT_B, SessionKey("fake-10"): ActorType.BOT_B,
    SessionKey("fake-11"): ActorType.BOT_C, SessionKey("fake-12"): ActorType.BOT_C,
    SessionKey("fake-13"): ActorType.BOT_D, SessionKey("fake-14"): ActorType.BOT_D,
}
EXPECTED_DETECTION_METRICS = {
    "bot_abd_detection_rate_percent": 5 / 6 * 100,
    "bot_c_detection_rate_percent": 50.0,
    "human_false_positive_rate_percent": 1 / 6 * 100,
}
EXPECTED_HUMAN_ROW = {VerdictStage.NORMAL: 4, VerdictStage.OBSERVE: 1, VerdictStage.CHALLENGE: 1, VerdictStage.HOLD: 0}
EXPECTED_GOLD_LATENCY_P95_SEC = 8.0


def _find_metric_mismatches(actual: dict[str, float], expected: dict[str, float]) -> list[str]:
    return [
        name for name, expected_value in expected.items()
        if name not in actual or not math.isclose(actual[name], expected_value)
    ]


class SelfCheckSuite:
    suite_name = "self_check"
    title = "QA Self-check"
    related_codes: tuple[str, ...] = ()

    def run(self, context: SuiteContext) -> SuiteResult:
        problems: list[str] = []

        correct_verdicts: SystemVerdicts = FakeVerdictReader().read_session_verdicts(context.run_id)
        detection_metrics = calculate_detection_metrics(FIXED_ANSWER_KEY, correct_verdicts)
        problems += [f"계산 오류: {name}" for name in _find_metric_mismatches(detection_metrics, EXPECTED_DETECTION_METRICS)]

        human_row = build_confusion_matrix(FIXED_ANSWER_KEY, correct_verdicts)[ActorType.HUMAN]
        if human_row != EXPECTED_HUMAN_ROW:
            problems.append("혼동 행렬 오류")

        gold_latency_p95_sec = calculate_p95(FakePipelineReader().read_gold_latency_sec(context.run_id))
        if not math.isclose(gold_latency_p95_sec, EXPECTED_GOLD_LATENCY_P95_SEC):
            problems.append("p95 계산 오류")

        wrong_verdicts = AlwaysWrongVerdictReader().read_session_verdicts(context.run_id)
        wrong_metrics = calculate_detection_metrics(FIXED_ANSWER_KEY, wrong_verdicts)
        if not _find_metric_mismatches(wrong_metrics, EXPECTED_DETECTION_METRICS):
            problems.append("오답 대상 미검출")

        context.report_progress(f"Self-check 이슈 {len(problems)}건")
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.FAILED if problems else SuiteOutcome.PASSED,
            metrics={"self_check_problem_count": float(len(problems))},
            message=" · ".join(problems),
        )
