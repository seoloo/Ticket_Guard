"""판정 정확도 · 탐지율 · 오탐률 · 기획서 21쪽 · 탐지 = CHALLENGE 이상"""
from ticket_guard_qa.answer_key.expected_verdicts import build_answer_key, plan_virtual_users
from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import (
    AnswerKey,
    PlannedUser,
    SessionKey,
    SuiteResult,
    SystemVerdicts,
    VirtualUserSessionResult,
)
from ticket_guard_qa.scoring.confusion_matrix import build_confusion_matrix
from ticket_guard_qa.scoring.detection_metrics import calculate_detection_metrics, find_false_positives, find_missed_bots
from ticket_guard_qa.scoring.latency_metrics import calculate_error_rate_percent, calculate_p95
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

MAX_LISTED_SESSION_COUNT = 200  # 04 · 05 화면 목록 길이


def send_virtual_user_traffic(
    context: SuiteContext, planned_users: list[PlannedUser]
) -> tuple[dict[str, SessionKey], list[VirtualUserSessionResult]]:
    """가상 사용자 라벨 → 시스템이 준 세션 키 · 시스템에는 행동 값만 보냄"""
    booking_api = context.system_target.booking_api
    session_key_by_label: dict[str, SessionKey] = {}
    session_results: list[VirtualUserSessionResult] = []
    for user in planned_users:
        behavior = context.bot_profile_registry.get_profile(user.actor_type).to_session_behavior()
        session_result = booking_api.start_virtual_user_session(behavior)
        session_key_by_label[user.virtual_user_label] = session_result.session_key
        session_results.append(session_result)
    return session_key_by_label, session_results


def build_result_details(answer_key: AnswerKey, system_verdicts: SystemVerdicts) -> dict:
    missed_bots = find_missed_bots(answer_key, system_verdicts)
    false_positives = find_false_positives(answer_key, system_verdicts)
    confusion_matrix = build_confusion_matrix(answer_key, system_verdicts)
    human_session_count = sum(1 for actor_type in answer_key.values() if not actor_type.is_bot)
    return {
        "session_count": len(answer_key),
        "human_session_count": human_session_count,
        "bot_session_count": len(answer_key) - human_session_count,
        "missed_bot_count": len(missed_bots),
        "false_positive_count": len(false_positives),
        "missed_bot_session_keys": missed_bots[:MAX_LISTED_SESSION_COUNT],
        "false_positive_session_keys": false_positives[:MAX_LISTED_SESSION_COUNT],
        "confusion_matrix": {
            actor_type.value: {stage.value: count for stage, count in row.items()}
            for actor_type, row in confusion_matrix.items()
        },
    }


class VerdictAccuracySuite:
    suite_name = "verdict_accuracy"
    title = "판정 정확도"
    related_codes: tuple[str, ...] = ()

    def run(self, context: SuiteContext) -> SuiteResult:
        run_config = context.run_config
        planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)
        context.report_progress(f"가상 사용자 {len(planned_users)}명 접속")
        session_key_by_label, session_results = send_virtual_user_traffic(context, planned_users)

        answer_key = build_answer_key(planned_users, session_key_by_label)
        context.answer_key_repository.save(context.run_id, answer_key)  # QA DB만
        context.report_progress(f"정답표 저장 · 세션 {len(answer_key)}개")

        system_verdicts = context.system_target.verdict_reader.read_session_verdicts(context.run_id)
        # 판정 API 응답 = 세션 시작 응답 · 실제 대상에서는 Locust 통계로 교체
        latency_values_sec = [result.latency_ms / 1000 for result in session_results]
        error_count = sum(1 for result in session_results if result.is_error)
        metrics = {
            **calculate_detection_metrics(answer_key, system_verdicts),
            "api_latency_p95_sec": calculate_p95(latency_values_sec),
            "api_error_rate_percent": calculate_error_rate_percent(len(session_results), error_count),
        }
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED,  # 측정 완료 · 합격은 합격 기준이 판단
            metrics=metrics,
            details=build_result_details(answer_key, system_verdicts),
        )
