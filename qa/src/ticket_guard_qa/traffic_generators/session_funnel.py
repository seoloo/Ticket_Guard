"""B3 유형별 퍼널 · VU 세션 결과 → 단계별 도달 인원 · 진입 → 대기열 → 보안문자 → 좌석 → 확정 · 판정은 판정 정확도 Suite"""
from collections import Counter

from ticket_guard_qa.domain.enums import BookingOutcome, SessionStep
from ticket_guard_qa.domain.models import ActorProgress, PlannedUser, VirtualUserSessionResult

PLANNED_PROGRESS_KEY = "PLANNED"
ACTOR_PROGRESS_DETAIL_KEY = "actor_progress"  # Suite details · 끝난 Run B3
TRAFFIC_FUNNEL_STEPS = (
    SessionStep.ENTERED, SessionStep.QUEUE_PASSED, SessionStep.CAPTCHA_PASSED, SessionStep.SEAT_SELECTED, SessionStep.CONFIRMED,
)
MOCK_FUNNEL_STEPS = (SessionStep.ENTERED, SessionStep.CONFIRMED)  # Mock = 단계별 소요 없음 · 나머지 '-'
STEP_LATENCY_KEY_BY_STEP = {  # Live 단계별 소요 키 = 그 단계 통과
    SessionStep.ENTERED: "start", SessionStep.QUEUE_PASSED: "queue", SessionStep.CAPTCHA_PASSED: "captcha",
}


def has_reached_step(result: VirtualUserSessionResult, step: SessionStep) -> bool:
    if step is SessionStep.CONFIRMED:
        return result.booking_outcome is BookingOutcome.BOOKED
    if step is SessionStep.SEAT_SELECTED:  # 원하는 좌석이 화면에서 전부 팔림 = 클릭 없음
        return result.step_latency_ms.get("seat_select", 0.0) > 0 or result.booking_outcome is BookingOutcome.BOOKED
    return STEP_LATENCY_KEY_BY_STEP[step] in result.step_latency_ms


def count_funnel_steps(
    planned_users: list[PlannedUser], results: list[VirtualUserSessionResult | None]
) -> dict[SessionStep, Counter]:
    finished = [(user, result) for user, result in zip(planned_users, results) if result is not None]
    if not any(result.step_latency_ms for _, result in finished):
        return {
            SessionStep.ENTERED: Counter(user.actor_type for user, _ in finished),
            SessionStep.CONFIRMED: Counter(user.actor_type for user, result in finished
                                           if result.booking_outcome is BookingOutcome.BOOKED),
        }
    return {
        step: Counter(user.actor_type for user, result in finished if has_reached_step(result, step))
        for step in TRAFFIC_FUNNEL_STEPS
    }


def build_actor_progress(planned_users: list[PlannedUser], reached_count_by_step: dict[SessionStep, Counter]) -> ActorProgress:
    planned_count_by_actor = Counter(user.actor_type for user in planned_users)
    return {
        actor_type.value: {
            PLANNED_PROGRESS_KEY: planned_count,
            **{step.value: counts[actor_type] for step, counts in reached_count_by_step.items()},
        }
        for actor_type, planned_count in planned_count_by_actor.items()
    }


def build_funnel_progress(planned_users: list[PlannedUser], results: list[VirtualUserSessionResult | None]) -> ActorProgress:
    return build_actor_progress(planned_users, count_funnel_steps(planned_users, results))
