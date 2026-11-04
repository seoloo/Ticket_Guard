"""봇 프로필 · B1 봇 목록 · B2 봇 설정 · 값은 시작값이며 B2에서 버전으로 바꿈"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import SessionBehavior


@dataclass(frozen=True)
class BotProfile:
    actor_type: ActorType
    display_name: str
    tool_name: str
    entry_delay_after_open_ms: int  # 오픈 후 첫 진입까지
    click_interval_mean_ms: int
    click_interval_deviation_ms: int
    sessions_per_device: int
    version_number: int = 1
    is_locked: bool = False  # 새 유형 · 평가 전용

    def to_session_behavior(self) -> SessionBehavior:
        return SessionBehavior(  # 시스템에는 행동 값만 · 종류 이름은 넘기지 않음
            entry_delay_after_open_ms=self.entry_delay_after_open_ms,
            click_interval_mean_ms=self.click_interval_mean_ms,
            click_interval_deviation_ms=self.click_interval_deviation_ms,
            sessions_per_device=self.sessions_per_device,
        )


DEFAULT_BOT_PROFILES: tuple[BotProfile, ...] = (
    BotProfile(ActorType.HUMAN, "가상 사람", "Locust", 3_000, 1_200, 600, 1),
    BotProfile(ActorType.BOT_A, "봇 A · 오픈 즉시형", "Locust", 0, 80, 5, 1),
    BotProfile(ActorType.BOT_B, "봇 B · 사람 흉내형", "Locust", 200, 400, 30, 1),
    BotProfile(ActorType.BOT_C, "봇 C · 브라우저 자동화", "Playwright", 500, 600, 150, 1),
    BotProfile(ActorType.BOT_D, "봇 D · 다중 세션", "Locust", 0, 150, 20, 8),
    BotProfile(ActorType.BOT_NEW, "새 유형", "Locust", 1_000, 900, 300, 1, is_locked=True),
)


class BotProfileRegistry:
    def __init__(self, profiles: tuple[BotProfile, ...] = DEFAULT_BOT_PROFILES) -> None:
        self.profile_by_actor_type = {profile.actor_type: profile for profile in profiles}

    def list_profiles(self) -> list[BotProfile]:
        return list(self.profile_by_actor_type.values())

    def get_profile(self, actor_type: ActorType) -> BotProfile:
        return self.profile_by_actor_type[actor_type]

    def save_new_version(self, profile: BotProfile) -> BotProfile:
        # TODO(B2 화면 구현 시): bot_versions 테이블에 저장 · 다음 02 시험에 반영
        raise NotImplementedError("봇 버전 저장 미구현")
