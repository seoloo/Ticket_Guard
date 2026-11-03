"""판정 정확도 · 탐지율 · 오탐률 · 기획서 21쪽 · 탐지 = CHALLENGE 이상"""
from ticket_guard_qa.answer_key.expected_verdicts import build_answer_key, plan_virtual_users
from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import PlannedUser, SessionKey, SuiteResult
from ticket_guard_qa.scoring.detection_metrics import calculate_detection_metrics
from ticket_guard_qa.test_suites.suite_interface import SuiteContext


def send_virtual_user_traffic(context: SuiteContext, planned_users: list[PlannedUser]) -> dict[str, SessionKey]:
    """가상 사용자 라벨 → 시스템이 준 세션 키"""
    # TODO(트래픽 생성기 구현 후): traffic_generators로 사람 · 봇 트래픽 보내기
    raise NotImplementedError("시스템 판정 없음 · 트래픽 생성기 미구현 · AGENTS.md 5장")


class VerdictAccuracySuite:
    suite_name = "verdict_accuracy"
    title = "판정 정확도"
    related_codes: tuple[str, ...] = ()

    def run(self, context: SuiteContext) -> SuiteResult:
        run_config = context.run_config
        planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)
        session_key_by_label = send_virtual_user_traffic(context, planned_users)

        answer_key = build_answer_key(planned_users, session_key_by_label)
        context.answer_key_repository.save(context.run_id, answer_key)  # QA DB만

        system_verdicts = context.system_target.verdict_reader.read_session_verdicts(context.run_id)
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED,  # 측정 완료 · 합격은 합격 기준이 판단
            metrics=calculate_detection_metrics(answer_key, system_verdicts),
        )
