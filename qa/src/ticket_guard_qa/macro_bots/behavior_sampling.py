"""행동 값 → 실제 대기 시간 뽑기 · 트래픽 생성기 · B3 진입 분포가 같은 식을 씀"""
import random

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import PlannedUser, SessionBehavior
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry


def pick_entry_delay_ms(behavior: SessionBehavior, random_source: random.Random) -> float:
    delay_ms = random_source.gauss(behavior.entry_delay_after_open_ms, behavior.entry_delay_deviation_ms)
    return max(delay_ms, 0.0)  # 오픈 전 진입 금지


def pick_click_interval_ms(behavior: SessionBehavior, random_source: random.Random) -> float:
    interval_ms = random_source.gauss(behavior.click_interval_mean_ms, behavior.click_interval_deviation_ms)
    return max(interval_ms, 0.0)  # 음수 간격 금지


def build_entry_histogram(
    planned_users: list[PlannedUser], registry: BotProfileRegistry, random_seed: int, bucket_ms: int, bucket_count: int
) -> dict[ActorType, list[int]]:
    """오픈 후 진입 시각 분포 · 마지막 칸 = 그 이후 전부 · 정답표 시드와 분리"""
    random_source = random.Random(f"entry-timing-{random_seed}")
    histogram = {actor_type: [0] * bucket_count for actor_type in registry.profile_by_actor_type}
    for user in planned_users:
        delay_ms = pick_entry_delay_ms(registry.get_profile(user.actor_type).behavior, random_source)
        histogram[user.actor_type][min(int(delay_ms // bucket_ms), bucket_count - 1)] += 1
    return histogram
