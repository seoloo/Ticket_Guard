"""봇 종류 소개 · 이름 · 용도 · 도구 · 색 · 버전과 상관없는 고정 정보 · 새 봇은 여기 한 줄부터"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import ActorType


@dataclass(frozen=True)
class BotTypeInfo:
    actor_type: ActorType
    display_name: str
    short_name: str  # 표 · 칩
    purpose: str
    tool_name: str
    color_token: str  # theme_tokens.css 변수 이름 · docs/ui.md 2장
    is_locked: bool = False  # 새 유형 · 평가 전용 · 설정 못 바꿈

    @property
    def slug(self) -> str:
        return self.actor_type.value.lower()  # 주소 /bots/{slug}


BOT_TYPE_CATALOG: tuple[BotTypeInfo, ...] = (
    BotTypeInfo(ActorType.HUMAN, "가상 사람", "사람", "오탐 기준선 · 사람다운 속도와 흔들림", "Locust", "bot-human"),
    BotTypeInfo(ActorType.BOT_A, "봇 A · 오픈 즉시형", "봇 A", "오픈 순간 일정한 간격으로 빠르게 진입", "Locust", "bot-a"),
    BotTypeInfo(ActorType.BOT_B, "봇 B · 사람 흉내형", "봇 B", "사람 속도를 흉내 내지만 간격이 일정함", "Locust", "bot-b"),
    BotTypeInfo(ActorType.BOT_C, "봇 C · 브라우저 자동화", "봇 C", "실제 브라우저로 화면을 따라 움직임", "Playwright", "bot-c"),
    BotTypeInfo(ActorType.BOT_D, "봇 D · 다중 세션", "봇 D", "한 기기에서 여러 세션을 동시에 엶", "Locust", "bot-d"),
    BotTypeInfo(ActorType.BOT_NEW, "새 유형", "새 유형", "규칙을 만들 때 보지 않은 행동 · 결과만 공개", "Locust", "bot-new", is_locked=True),
)

BOT_TYPE_INFO_BY_ACTOR_TYPE = {info.actor_type: info for info in BOT_TYPE_CATALOG}


def get_bot_type_info(actor_type: ActorType) -> BotTypeInfo:
    return BOT_TYPE_INFO_BY_ACTOR_TYPE[actor_type]


def find_bot_type_by_slug(slug: str) -> BotTypeInfo | None:
    return next((info for info in BOT_TYPE_CATALOG if info.slug == slug.lower()), None)
