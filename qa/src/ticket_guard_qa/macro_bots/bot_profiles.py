"""봇 프로필 = 종류 + 행동 값 + 버전 · 기본값은 v1 · B2에서 저장한 버전은 bot_profile_store"""
from dataclasses import dataclass
from datetime import datetime

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.macro_bots.bot_catalog import BotTypeInfo, find_bot_type_info, get_bot_type_info, list_bot_types

DEFAULT_VERSION_NUMBER = 1

# 시작값 · 예시 · 실제 시험 전에 B2에서 조정
DEFAULT_BEHAVIOR_BY_ACTOR_TYPE: dict[ActorType, SessionBehavior] = {
    ActorType.HUMAN: SessionBehavior(
        entry_delay_after_open_ms=3_000, entry_delay_deviation_ms=2_000,
        click_interval_mean_ms=1_200, click_interval_deviation_ms=600,
        browse_page_count=3, page_dwell_mean_ms=4_000, page_dwell_deviation_ms=2_500, sessions_per_device=1,
        sold_out_retry_count=2, sold_out_retry_delay_ms=1_500, browser_trace_level=1,
    ),
    ActorType.BOT_A: SessionBehavior(
        entry_delay_after_open_ms=0, entry_delay_deviation_ms=20,
        click_interval_mean_ms=80, click_interval_deviation_ms=5,
        browse_page_count=0, page_dwell_mean_ms=0, page_dwell_deviation_ms=0, sessions_per_device=1,
        sold_out_retry_count=10, sold_out_retry_delay_ms=0, browser_trace_level=0,
    ),
    ActorType.BOT_B: SessionBehavior(
        entry_delay_after_open_ms=200, entry_delay_deviation_ms=150,
        click_interval_mean_ms=400, click_interval_deviation_ms=30,
        browse_page_count=1, page_dwell_mean_ms=1_500, page_dwell_deviation_ms=100, sessions_per_device=1,
        sold_out_retry_count=3, sold_out_retry_delay_ms=400, browser_trace_level=1,
    ),
    ActorType.BOT_C: SessionBehavior(
        entry_delay_after_open_ms=500, entry_delay_deviation_ms=300,
        click_interval_mean_ms=600, click_interval_deviation_ms=150,
        browse_page_count=1, page_dwell_mean_ms=2_000, page_dwell_deviation_ms=200, sessions_per_device=1,
        sold_out_retry_count=1, sold_out_retry_delay_ms=600, browser_trace_level=1,
    ),
    ActorType.BOT_D: SessionBehavior(
        entry_delay_after_open_ms=0, entry_delay_deviation_ms=50,
        click_interval_mean_ms=150, click_interval_deviation_ms=20,
        browse_page_count=0, page_dwell_mean_ms=0, page_dwell_deviation_ms=0, sessions_per_device=8,
        sold_out_retry_count=3, sold_out_retry_delay_ms=150, browser_trace_level=0,
    ),
    ActorType.BOT_NEW: SessionBehavior(
        entry_delay_after_open_ms=1_000, entry_delay_deviation_ms=500,
        click_interval_mean_ms=900, click_interval_deviation_ms=300,
        browse_page_count=2, page_dwell_mean_ms=2_500, page_dwell_deviation_ms=800, sessions_per_device=1,
        sold_out_retry_count=2, sold_out_retry_delay_ms=900, browser_trace_level=1,
    ),
}


@dataclass(frozen=True)
class BotProfile:
    actor_type: ActorType
    behavior: SessionBehavior  # 시스템에는 이 값만 · 종류 이름은 넘기지 않음
    version_number: int = DEFAULT_VERSION_NUMBER
    change_note: str = ""
    saved_at: datetime | None = None  # None = 기본값

    @property
    def type_info(self) -> BotTypeInfo:
        return get_bot_type_info(self.actor_type)


def find_default_behavior(actor_type: ActorType) -> SessionBehavior:
    """v1 행동 값 · 기본 유형 = 위 표 · 추가 유형 = QA DB bot_types 시작 값 · 모르는 유형 = 정상 값"""
    if actor_type in DEFAULT_BEHAVIOR_BY_ACTOR_TYPE:
        return DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[actor_type]
    info = find_bot_type_info(actor_type)
    if info is not None and info.initial_behavior is not None:
        return info.initial_behavior
    return DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN]


def build_default_profiles() -> tuple[BotProfile, ...]:
    """목록의 모든 유형 v1 · 추가 유형 포함"""
    return tuple(
        BotProfile(info.actor_type, find_default_behavior(info.actor_type), change_note="초기값")
        for info in list_bot_types()
    )


class BotProfileRegistry:
    """한 시점의 프로필 묶음 · 실행 하나는 시작할 때 받은 묶음만 씀 (도중 저장 영향 없음)"""

    def __init__(self, profiles: tuple[BotProfile, ...] | None = None) -> None:
        self.profile_by_actor_type = {profile.actor_type: profile for profile in profiles or build_default_profiles()}

    def list_profiles(self) -> list[BotProfile]:
        return list(self.profile_by_actor_type.values())

    def get_profile(self, actor_type: ActorType) -> BotProfile:
        if actor_type not in self.profile_by_actor_type:  # 실행 도중 추가된 유형 · 기본값
            return BotProfile(ActorType(actor_type), find_default_behavior(ActorType(actor_type)), change_note="초기값")
        return self.profile_by_actor_type[actor_type]

    def version_number_by_actor_type(self) -> dict[str, int]:
        return {actor_type.value: profile.version_number for actor_type, profile in self.profile_by_actor_type.items()}
