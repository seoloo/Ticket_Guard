"""봇 종류 소개 · 이름 · 역할 · 설명 · 탐지 신호 · 트래픽 종류 · 색 · 버전과 상관없는 고정 정보 · 새 봇은 여기 한 줄부터"""
from dataclasses import dataclass
from enum import Enum

from ticket_guard_qa.domain.enums import ActorType


class BotRole(Enum):
    """B1 구획 · 무엇을 재는 트래픽인지"""
    BASELINE = "baseline"  # 정상 트래픽 · 오탐률
    DETECTION_TARGET = "detection_target"  # 봇 A ~ D · 탐지율
    EVALUATION_ONLY = "evaluation_only"  # 미학습 유형 · 결과 공개만


@dataclass(frozen=True)
class BotRoleInfo:
    role: BotRole
    title: str
    description: str


BOT_ROLE_CATALOG: tuple[BotRoleInfo, ...] = (  # B1 구획 순서
    BotRoleInfo(BotRole.BASELINE, "기준 트래픽", "일반 관람객 예매 행동 재현 · 정상 사용자를 봇으로 잘못 판정하는 비율(오탐률) 측정"),
    BotRoleInfo(BotRole.DETECTION_TARGET, "탐지 대상 봇", "실제 매크로 수법 4종 재현 · 봇 세션을 봇으로 판정하는 비율(탐지율) 측정"),
    BotRoleInfo(BotRole.EVALUATION_ONLY, "평가 전용 봇", "탐지 규칙 학습에 쓰지 않은 행동 패턴 · 처음 보는 봇 탐지 능력 측정 · 설정 변경 불가"),
)


@dataclass(frozen=True)
class BotTypeInfo:
    actor_type: ActorType
    display_name: str
    short_name: str  # 표 · 칩
    purpose: str  # 한 줄 정의 · 처음 보는 사람 기준
    traffic_channel: str  # 화면 태그 · 도구 이름(Locust 등)은 화면에 쓰지 않음
    color_token: str  # theme_tokens.css 변수 이름 · docs/ui.md 2장
    role: BotRole
    icon_name: str  # lucide 아이콘
    detection_signals: tuple[str, ...]  # 탐지 시스템이 잡아야 할 흔적 · 행동 값과 무관한 고정 설명
    is_locked: bool = False  # 새 유형 · 평가 전용 · 설정 못 바꿈

    @property
    def slug(self) -> str:
        return self.actor_type.value.lower()  # 주소 /bots/{slug}

    @property
    def type_name(self) -> str:
        """봇 A 같은 앞머리 없는 이름 · 카드 제목"""
        return self.display_name.split(" · ")[-1]

    @property
    def role_label(self) -> str:
        """카드 머리 작은 글씨 · 봇 A 등"""
        if self.role is BotRole.DETECTION_TARGET:
            return f"봇 {self.short_name}"
        return get_bot_role_info(self.role).title


HTTP_TRAFFIC = "HTTP 트래픽"  # Locust
BROWSER_TRAFFIC = "브라우저 트래픽"  # Playwright


BOT_TYPE_CATALOG: tuple[BotTypeInfo, ...] = (
    BotTypeInfo(
        ActorType.HUMAN, "정상 트래픽", "정상", "일반 관람객의 실제 예매 행동을 재현한 가상 사용자",
        HTTP_TRAFFIC, "bot-human", BotRole.BASELINE, "user-round",
        ("예매 시작 시각이 사람마다 넓게 퍼짐", "좌석 클릭 간격이 매번 다름", "공연 목록 · 상세 화면 조회 기록 존재"),
    ),
    BotTypeInfo(
        ActorType.BOT_A, "봇 A · 고속 반복 매크로", "A", "예매 오픈 순간 매우 짧고 일정한 간격으로 요청을 반복 전송하는 매크로",
        HTTP_TRAFFIC, "bot-a", BotRole.DETECTION_TARGET, "zap",
        ("예매 시작 시각이 예매 오픈 시각과 거의 일치", "좌석 클릭 간격이 매번 거의 같음", "화면 조회 없이 예매 요청만 전송"),
    ),
    BotTypeInfo(
        ActorType.BOT_B, "봇 B · 위장 매크로", "B", "사람과 비슷한 속도로 요청하지만 클릭 간격이 지나치게 일정한 매크로",
        HTTP_TRAFFIC, "bot-b", BotRole.DETECTION_TARGET, "venetian-mask",
        ("클릭 속도는 사람 수준 · 간격 편차는 사람보다 훨씬 작음", "화면마다 머무는 시간이 매번 비슷", "항상 같은 화면 순서로 이동"),
    ),
    BotTypeInfo(
        ActorType.BOT_C, "봇 C · 브라우저 자동화 매크로", "C", "화면 없는 브라우저로 예매 화면 버튼을 자동 클릭하는 매크로",
        BROWSER_TRAFFIC, "bot-c", BotRole.DETECTION_TARGET, "monitor-smartphone",
        ("화면 조회 기록 존재 · 사람과 가장 비슷한 흔적", "화면마다 머무는 시간이 일정", "마우스 이동 없이 버튼만 클릭"),
    ),
    BotTypeInfo(
        ActorType.BOT_D, "봇 D · 세션 복제 매크로", "D", "기기 1대에서 예매 창 여러 개를 동시에 열어 대기열에 한꺼번에 들어가는 매크로",
        HTTP_TRAFFIC, "bot-d", BotRole.DETECTION_TARGET, "copy",
        ("같은 기기에서 예매 창 여러 개 동시 접속", "여러 계정이 같은 시각에 대기열 진입", "기기 · 브라우저 정보가 모두 같음"),
    ),
    BotTypeInfo(
        ActorType.BOT_NEW, "미학습 유형 봇", "미학습", "탐지 규칙을 만들 때 쓰지 않은 행동 패턴의 봇",
        HTTP_TRAFFIC, "bot-new", BotRole.EVALUATION_ONLY, "lock",
        ("탐지 규칙 학습에 쓰지 않은 행동 조합", "판정 결과만으로 처음 보는 봇 탐지 능력 확인"),
        is_locked=True,
    ),
)

BOT_TYPE_INFO_BY_ACTOR_TYPE = {info.actor_type: info for info in BOT_TYPE_CATALOG}
BOT_ROLE_INFO_BY_ROLE = {info.role: info for info in BOT_ROLE_CATALOG}


def get_bot_type_info(actor_type: ActorType) -> BotTypeInfo:
    return BOT_TYPE_INFO_BY_ACTOR_TYPE[actor_type]


def get_bot_role_info(role: BotRole) -> BotRoleInfo:
    return BOT_ROLE_INFO_BY_ROLE[role]


def find_bot_type_by_slug(slug: str) -> BotTypeInfo | None:
    return next((info for info in BOT_TYPE_CATALOG if info.slug == slug.lower()), None)
