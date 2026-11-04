"""봇 종류 소개 · 이름 · 용도 · 트래픽 종류 · 색 · 버전과 상관없는 고정 정보 · 새 봇은 여기 한 줄부터"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import ActorType


@dataclass(frozen=True)
class BotTypeInfo:
    actor_type: ActorType
    display_name: str
    short_name: str  # 표 · 칩
    purpose: str
    traffic_channel: str  # 화면 태그 · 도구 이름(Locust 등)은 화면에 쓰지 않음
    color_token: str  # theme_tokens.css 변수 이름 · docs/ui.md 2장
    is_locked: bool = False  # 새 유형 · 평가 전용 · 설정 못 바꿈

    @property
    def slug(self) -> str:
        return self.actor_type.value.lower()  # 주소 /bots/{slug}


HTTP_TRAFFIC = "HTTP 트래픽"  # Locust
BROWSER_TRAFFIC = "브라우저 트래픽"  # Playwright


BOT_TYPE_CATALOG: tuple[BotTypeInfo, ...] = (
    BotTypeInfo(ActorType.HUMAN, "정상 트래픽", "정상", "오탐률 기준 트래픽 · 진입 시각 분산 · 클릭 간격 분산 큼", HTTP_TRAFFIC, "bot-human"),
    BotTypeInfo(ActorType.BOT_A, "봇 A · 고속 반복 매크로", "A", "오픈 시각 고정 진입 · 고속 정주기 요청", HTTP_TRAFFIC, "bot-a"),
    BotTypeInfo(ActorType.BOT_B, "봇 B · 위장 매크로", "B", "사람 수준 요청 속도 · 낮은 간격 분산", HTTP_TRAFFIC, "bot-b"),
    BotTypeInfo(ActorType.BOT_C, "봇 C · 브라우저 자동화 매크로", "C", "헤드리스 브라우저 기반 화면 흐름 재현", BROWSER_TRAFFIC, "bot-c"),
    BotTypeInfo(ActorType.BOT_D, "봇 D · 세션 복제 매크로", "D", "단일 기기 다중 세션 병렬 접속", HTTP_TRAFFIC, "bot-d"),
    BotTypeInfo(ActorType.BOT_NEW, "미학습 유형 봇", "미학습", "미학습 행동 패턴 · 일반화 성능 측정용", HTTP_TRAFFIC, "bot-new", is_locked=True),
)

BOT_TYPE_INFO_BY_ACTOR_TYPE = {info.actor_type: info for info in BOT_TYPE_CATALOG}


def get_bot_type_info(actor_type: ActorType) -> BotTypeInfo:
    return BOT_TYPE_INFO_BY_ACTOR_TYPE[actor_type]


def find_bot_type_by_slug(slug: str) -> BotTypeInfo | None:
    return next((info for info in BOT_TYPE_CATALOG if info.slug == slug.lower()), None)
