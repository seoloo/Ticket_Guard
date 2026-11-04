"""가상 사용자 계획 · 누가 봇인지 정하는 유일한 곳"""
import random

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import AnswerKey, PlannedUser, SessionKey, TrafficMix

VIRTUAL_USER_LABEL_PREFIX = "qa-"


def count_users_by_actor_type(traffic_mix: TrafficMix, virtual_user_count: int) -> dict[ActorType, int]:
    exact_counts = {
        actor_type: virtual_user_count * percent / 100
        for actor_type, percent in traffic_mix.percent_by_actor_type().items()
    }
    counts = {actor_type: int(exact) for actor_type, exact in exact_counts.items()}
    leftover = virtual_user_count - sum(counts.values())
    by_remainder = sorted(exact_counts, key=lambda actor_type: exact_counts[actor_type] - counts[actor_type], reverse=True)
    for actor_type in by_remainder[:leftover]:  # 반올림 오차 = 나머지 큰 순서로
        counts[actor_type] += 1
    return counts


def plan_virtual_users(traffic_mix: TrafficMix, virtual_user_count: int, random_seed: int) -> list[PlannedUser]:
    actor_types = [
        actor_type
        for actor_type, count in count_users_by_actor_type(traffic_mix, virtual_user_count).items()
        for _ in range(count)
    ]
    random.Random(random_seed).shuffle(actor_types)  # 번호 순서로 봇 여부 추측 금지
    return [
        PlannedUser(f"{VIRTUAL_USER_LABEL_PREFIX}{index:04d}", actor_type)
        for index, actor_type in enumerate(actor_types, start=1)
    ]


def build_answer_key(planned_users: list[PlannedUser], session_key_by_label: dict[str, SessionKey]) -> AnswerKey:
    """트래픽 후 시스템이 준 세션 키와 연결 · 연결 안 된 사용자는 빠짐"""
    return {
        session_key_by_label[user.virtual_user_label]: user.actor_type
        for user in planned_users
        if user.virtual_user_label in session_key_by_label
    }
