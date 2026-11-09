"""판정 정확도 · 탐지율 · 오탐률 · 기획서 21쪽 · 탐지 = CHALLENGE 이상"""
from collections import Counter

from ticket_guard_qa.answer_key.expected_verdicts import build_answer_key, plan_virtual_users
from ticket_guard_qa.domain.enums import BookingOutcome, SessionStep, SuiteOutcome
from ticket_guard_qa.domain.models import (
    ActorProgress,
    AnswerKey,
    PlannedUser,
    SessionKey,
    SuiteResult,
    SystemVerdicts,
    VirtualUserSessionResult,
)
from ticket_guard_qa.scoring.confusion_matrix import build_confusion_matrix
from ticket_guard_qa.scoring.detection_breakdown import count_rule_hits
from ticket_guard_qa.scoring.detection_metrics import calculate_detection_metrics, find_false_positives, find_missed_bots
from ticket_guard_qa.scoring.latency_metrics import calculate_error_rate_percent, calculate_p95
from ticket_guard_qa.test_suites.suite_interface import SuiteContext, SuiteGuide
from ticket_guard_qa.traffic_generators.virtual_user_traffic import (
    build_planned_user_session_plans,
    save_browser_captures,
    reset_before_traffic,
    send_virtual_user_traffic,
)

VERDICT_ACCURACY_SUITE_NAME = "verdict_accuracy"  # 04 · B1 · B4가 결과를 찾는 이름
MAX_LISTED_SESSION_COUNT = 200  # 04 · 05 화면 목록 길이
PLANNED_PROGRESS_KEY = "PLANNED"


def build_actor_progress(planned_users: list[PlannedUser], reached_count_by_step: dict[SessionStep, Counter]) -> ActorProgress:
    planned_count_by_actor = Counter(user.actor_type for user in planned_users)
    return {
        actor_type.value: {
            PLANNED_PROGRESS_KEY: planned_count,
            **{step.value: counts[actor_type] for step, counts in reached_count_by_step.items()},
        }
        for actor_type, planned_count in planned_count_by_actor.items()
    }


def count_reached_steps(
    planned_users: list[PlannedUser], results: list[VirtualUserSessionResult | None]
) -> dict[SessionStep, Counter]:
    finished = [(user, result) for user, result in zip(planned_users, results) if result is not None]
    return {
        SessionStep.ENTERED: Counter(user.actor_type for user, _ in finished),
        SessionStep.CONFIRMED: Counter(
            user.actor_type for user, result in finished if result.booking_outcome is BookingOutcome.BOOKED
        ),
    }


def send_planned_user_traffic(
    context: SuiteContext, planned_users: list[PlannedUser]
) -> tuple[dict[str, SessionKey], list[VirtualUserSessionResult]]:
    """가상 사용자 라벨 → 시스템이 준 세션 키 · 시스템에는 행동 값만 보냄 · VU 동시 실행"""
    booking_api = context.system_target.booking_api
    context.report_progress(reset_before_traffic(booking_api))

    def report_traffic_progress(results: list[VirtualUserSessionResult | None]) -> None:
        finished_count = sum(result is not None for result in results)
        context.report_progress(
            f"Entered {finished_count}/{len(planned_users)}",
            actor_progress=build_actor_progress(planned_users, count_reached_steps(planned_users, results)),
        )

    session_results = send_virtual_user_traffic(
        booking_api, build_planned_user_session_plans(planned_users, context.bot_profile_registry, context.run_config.random_seed),
        context.run_config.duration_sec, report_traffic_progress,
    )
    save_browser_captures(context.report_output_dir, context.run_id, planned_users, session_results)  # B3 브라우저 화면
    session_key_by_label = {
        user.virtual_user_label: result.session_key for user, result in zip(planned_users, session_results)
    }
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


def read_rule_hit_counts_or_none(context: SuiteContext) -> dict[str, int] | None:
    """SESSION_VERDICTS.matchedRules · 시스템이 아직 판정 이유를 안 주면 None · B4 룰 메타데이터 미수신 표시"""
    try:
        return count_rule_hits(context.system_target.verdict_reader.read_verdict_records(context.run_id))
    except NotImplementedError:
        return None


class VerdictAccuracySuite:
    suite_name = VERDICT_ACCURACY_SUITE_NAME
    title = "판정 정확도"
    related_codes: tuple[str, ...] = ("E22",)  # 보류 판정
    guide = SuiteGuide(
        "시스템이 매크로는 매크로로, 사람은 사람으로 판정",
        "누가 봇인지 적은 정답표와 시스템 판정 비교",
        "매크로 탐지 90% 이상(브라우저 자동화 70%) · 사람 오판 1% 이하",
    )

    def run(self, context: SuiteContext) -> SuiteResult:
        run_config = context.run_config
        planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)
        context.report_progress(f"VU {len(planned_users)} 접속")
        session_key_by_label, session_results = send_planned_user_traffic(context, planned_users)

        answer_key = build_answer_key(planned_users, session_key_by_label)
        context.answer_key_repository.save(context.run_id, answer_key)  # QA DB만
        context.report_progress(f"Ground Truth 저장 · {len(answer_key)}세션")

        system_verdicts = context.system_target.verdict_reader.read_session_verdicts(context.run_id)
        rule_hit_count_by_rule_id = read_rule_hit_counts_or_none(context)
        context.report_progress(f"Verdict {len(system_verdicts)}", actor_progress=build_actor_progress(planned_users, {
            SessionStep.ENTERED: Counter(answer_key.values()),
            SessionStep.VERDICT_RECEIVED: Counter(answer_key[key] for key in answer_key if key in system_verdicts),
        }))
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
            details={**build_result_details(answer_key, system_verdicts), "rule_hit_count_by_rule_id": rule_hit_count_by_rule_id},
        )
