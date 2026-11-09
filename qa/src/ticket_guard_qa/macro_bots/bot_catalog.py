"""봇 유형 목록 한 곳 · 기본 6종(코드) + 화면에서 추가한 유형(QA DB bot_types) · 이름 · 분류 · 상태 · 설명 · 탐지 흔적 · 색"""
from dataclasses import dataclass, replace
from enum import Enum

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import SessionBehavior


class BotRole(Enum):
    """무엇을 재는 트래픽인지"""
    BASELINE = "baseline"  # 정상 트래픽 · 오탐률
    DETECTION_TARGET = "detection_target"  # 봇 · 탐지율
    EVALUATION_ONLY = "evaluation_only"  # 미학습 유형 · 결과 공개만


class BotStatus(Enum):
    """봇 수명 주기 · 작성 중은 Run 제외 · 검증 중 · 사용 중은 Run 포함"""
    DRAFT = "draft"
    REVIEW = "review"
    ACTIVE = "active"

    @property
    def title(self) -> str:
        return {BotStatus.DRAFT: "작성 중", BotStatus.REVIEW: "검증 중", BotStatus.ACTIVE: "사용 중"}[self]

    @property
    def is_in_runs(self) -> bool:
        return self is not BotStatus.DRAFT


@dataclass(frozen=True)
class BotCategory:
    """공격 수법 분류 · B1 분류 타일 · 표 묶음 순서 = 목록 순서"""
    category_id: str
    title: str
    description: str
    icon_name: str  # lucide 아이콘
    is_selectable: bool = True  # 새 봇 추가에서 고를 수 있는 분류


BOT_CATEGORIES: tuple[BotCategory, ...] = (
    BotCategory("baseline", "기준 트래픽", "일반 관람객 예매 행동 · 오탐률 기준", "user-round", is_selectable=False),
    BotCategory("request_automation", "요청 자동화", "화면 없이 예매 요청을 짧은 주기로 직접 전송", "zap"),
    BotCategory("behavior_disguise", "행동 위장", "사람과 비슷한 속도 · 지나치게 일정한 행동", "venetian-mask"),
    BotCategory("browser_automation", "브라우저 자동화", "실제 화면을 띄워 버튼 자동 클릭", "monitor-smartphone"),
    BotCategory("session_device", "세션 · 기기 위장", "기기 1대 여러 세션 · 기기 정보 조작", "copy"),
    BotCategory("captcha_bypass", "보안문자 우회", "보안문자 자동 판독 · 반복 시도", "scan-text"),
    BotCategory("inventory_hoarding", "재고 선점", "좌석 점유 반복 · 취소표 감시", "armchair"),
    BotCategory("evaluation", "평가 전용", "탐지 규칙 학습 미사용 · 결과만 공개", "lock", is_selectable=False),
)
BOT_CATEGORY_BY_ID = {category.category_id: category for category in BOT_CATEGORIES}

# 화면에서 추가한 유형 색 · 순서대로 · 주황은 DB 전용이라 제외 · 다 쓰면 처음부터 (알파벳 코드로 구분)
CUSTOM_BOT_COLORS: tuple[str, ...] = (
    "#DB2777", "#0284C7", "#65A30D", "#4F46E5", "#0D9488", "#C026D3", "#0891B2", "#BE123C", "#15803D", "#9333EA",
)


@dataclass(frozen=True)
class BotTypeInfo:
    actor_type: ActorType
    display_name: str
    short_name: str  # 알파벳 코드 · 표 · 칩 · 배지
    purpose: str  # 한 줄 정의 · 처음 보는 사람 기준
    traffic_channel: str  # 화면 태그 · 도구 이름(Locust 등)은 화면에 쓰지 않음
    color_token: str  # CSS 변수 이름 · 기본 = theme_tokens.css · 추가 유형 = layout.html이 color_hex로 정의
    role: BotRole
    icon_name: str  # lucide 아이콘
    detection_signals: tuple[str, ...]  # 탐지 시스템이 잡아야 할 흔적
    category_id: str
    detection_target_id: str | None  # 합격 기준 묶음 · domain/detection_targets · None = 결과 공개만
    status: BotStatus = BotStatus.ACTIVE
    is_locked: bool = False  # 평가 전용 · 설정 못 바꿈
    is_custom: bool = False  # 화면에서 추가 · QA DB bot_types
    color_hex: str = ""  # 추가 유형만
    initial_behavior: SessionBehavior | None = None  # 추가 유형 v1 행동 값 · 기본 유형은 bot_profiles 기본값

    @property
    def slug(self) -> str:
        return self.actor_type.value.lower()  # 주소 /bots/{slug}

    @property
    def type_name(self) -> str:
        """봇 A 같은 앞머리 없는 이름 · 카드 제목"""
        return self.display_name.split(" · ")[-1]

    @property
    def role_label(self) -> str:
        """이름 위 작은 글씨 · 봇 A 등"""
        if self.role is BotRole.DETECTION_TARGET:
            return f"봇 {self.short_name}"
        return self.category.title

    @property
    def category(self) -> BotCategory:
        return BOT_CATEGORY_BY_ID.get(self.category_id, BOT_CATEGORY_BY_ID["request_automation"])

    @property
    def status_title(self) -> str:
        return "평가 전용" if self.role is BotRole.EVALUATION_ONLY else self.status.title

    @property
    def status_key(self) -> str:
        """상태 칩 CSS · draft · review · active · locked"""
        return "locked" if self.role is BotRole.EVALUATION_ONLY else self.status.value

    @property
    def is_in_traffic_mix(self) -> bool:
        """02 트래픽 구성에 나오는 유형 · 평가 전용 · 작성 중 제외"""
        return self.role is not BotRole.EVALUATION_ONLY and self.status.is_in_runs


HTTP_TRAFFIC = "HTTP 트래픽"  # Locust
BROWSER_TRAFFIC = "브라우저 트래픽"  # Playwright


BUILT_IN_BOT_TYPES: tuple[BotTypeInfo, ...] = (
    BotTypeInfo(
        ActorType.HUMAN, "정상 트래픽", "정상", "일반 관람객의 실제 예매 행동을 재현한 가상 사용자",
        HTTP_TRAFFIC, "bot-human", BotRole.BASELINE, "user-round",
        ("예매 시작 시각이 사람마다 넓게 퍼짐", "좌석 클릭 간격이 매번 다름", "공연 목록 · 상세 화면 조회 기록 존재"),
        "baseline", "human_false_positive",
    ),
    BotTypeInfo(
        ActorType.BOT_A, "봇 A · 고속 반복 매크로", "A", "예매 오픈 순간 매우 짧고 일정한 간격으로 요청을 반복 전송하는 매크로",
        HTTP_TRAFFIC, "bot-a", BotRole.DETECTION_TARGET, "zap",
        ("예매 시작 시각이 예매 오픈 시각과 거의 일치", "좌석 클릭 간격이 매번 거의 같음", "화면 조회 없이 예매 요청만 전송"),
        "request_automation", "bot_abd_detection",
    ),
    BotTypeInfo(
        ActorType.BOT_B, "봇 B · 위장 매크로", "B", "사람과 비슷한 속도로 요청하지만 클릭 간격이 지나치게 일정한 매크로",
        HTTP_TRAFFIC, "bot-b", BotRole.DETECTION_TARGET, "venetian-mask",
        ("클릭 속도는 사람 수준 · 간격 편차는 사람보다 훨씬 작음", "화면마다 머무는 시간이 매번 비슷", "항상 같은 화면 순서로 이동"),
        "behavior_disguise", "bot_abd_detection",
    ),
    BotTypeInfo(
        ActorType.BOT_C, "봇 C · 브라우저 자동화 매크로", "C", "화면 없는 브라우저로 예매 화면 버튼을 자동 클릭하는 매크로",
        BROWSER_TRAFFIC, "bot-c", BotRole.DETECTION_TARGET, "monitor-smartphone",
        ("화면 조회 기록 존재 · 사람과 가장 비슷한 흔적", "화면마다 머무는 시간이 일정", "마우스 이동 없이 버튼만 클릭"),
        "browser_automation", "bot_c_detection",
    ),
    BotTypeInfo(
        ActorType.BOT_D, "봇 D · 세션 복제 매크로", "D", "기기 1대에서 예매 창 여러 개를 동시에 열어 대기열에 한꺼번에 들어가는 매크로",
        HTTP_TRAFFIC, "bot-d", BotRole.DETECTION_TARGET, "copy",
        ("같은 기기에서 예매 창 여러 개 동시 접속", "여러 계정이 같은 시각에 대기열 진입", "기기 · 브라우저 정보가 모두 같음"),
        "session_device", "bot_abd_detection",
    ),
    BotTypeInfo(
        ActorType.BOT_NEW, "미학습 유형 봇", "미학습", "탐지 규칙을 만들 때 쓰지 않은 행동 패턴의 봇",
        HTTP_TRAFFIC, "bot-new", BotRole.EVALUATION_ONLY, "lock",
        ("탐지 규칙 학습에 쓰지 않은 행동 조합", "판정 결과만으로 처음 보는 봇 탐지 능력 확인"),
        "evaluation", None, is_locked=True,
    ),
)
BOT_TYPE_CATALOG = BUILT_IN_BOT_TYPES  # 이전 이름 호환

_custom_bot_types: tuple[BotTypeInfo, ...] = ()  # QA DB에서 읽은 추가 유형 · bot_type_store가 갱신


def replace_custom_bot_types(custom_types: tuple[BotTypeInfo, ...]) -> None:
    """QA DB bot_types 최신 상태로 교체 · 화면 · 실행이 같은 목록을 보게"""
    global _custom_bot_types
    _custom_bot_types = tuple(custom_types)


def list_bot_types() -> tuple[BotTypeInfo, ...]:
    """분류 순서 → 기본 유형 → 추가 유형 순"""
    category_order = {category.category_id: index for index, category in enumerate(BOT_CATEGORIES)}
    all_types = (*BUILT_IN_BOT_TYPES, *_custom_bot_types)
    return tuple(sorted(all_types, key=lambda info: (category_order.get(info.category_id, 99), info.is_custom, info.short_name)))


def list_actor_types() -> tuple[ActorType, ...]:
    return tuple(info.actor_type for info in list_bot_types())


def find_bot_type_info(actor_type: ActorType | str) -> BotTypeInfo | None:
    return next((info for info in (*BUILT_IN_BOT_TYPES, *_custom_bot_types) if info.actor_type == actor_type), None)


def get_bot_type_info(actor_type: ActorType | str) -> BotTypeInfo:
    """목록에 없는 유형(삭제 · 다른 DB) = 이름만 있는 회색 정보 · 화면이 깨지지 않게"""
    info = find_bot_type_info(actor_type)
    if info is not None:
        return info
    actor_type = ActorType(actor_type)
    return BotTypeInfo(actor_type, actor_type.value, actor_type.value.removeprefix("BOT_"), "목록에 없는 봇 유형",
                       HTTP_TRAFFIC, "bot-new", BotRole.DETECTION_TARGET, "help-circle", (), "request_automation", None,
                       is_locked=True)


def get_bot_role_info(role: BotRole) -> BotCategory:
    """역할 → 대표 분류 · 이전 화면 호환"""
    return BOT_CATEGORY_BY_ID[{BotRole.BASELINE: "baseline", BotRole.EVALUATION_ONLY: "evaluation"}.get(role, "request_automation")]


def find_bot_type_by_slug(slug: str) -> BotTypeInfo | None:
    return next((info for info in list_bot_types() if info.slug == slug.lower()), None)


def build_custom_bot_type(
    actor_type: ActorType, display_name: str, short_name: str, purpose: str, category_id: str, color_hex: str,
    detection_signals: tuple[str, ...], detection_target_id: str | None, status: BotStatus,
    initial_behavior: SessionBehavior, traffic_channel: str = HTTP_TRAFFIC,
) -> BotTypeInfo:
    category = BOT_CATEGORY_BY_ID.get(category_id, BOT_CATEGORY_BY_ID["request_automation"])
    return BotTypeInfo(
        actor_type, f"봇 {short_name} · {display_name}", short_name, purpose, traffic_channel,
        f"bot-custom-{short_name.lower()}", BotRole.DETECTION_TARGET, category.icon_name, detection_signals,
        category.category_id, detection_target_id, status=status, is_custom=True, color_hex=color_hex,
        initial_behavior=initial_behavior,
    )


def with_status(info: BotTypeInfo, status: BotStatus) -> BotTypeInfo:
    return replace(info, status=status)
