"""용어집의 고정 값 · AGENTS.md 10장"""
from enum import StrEnum


class VerdictStage(StrEnum):
    NORMAL = "NORMAL"
    OBSERVE = "OBSERVE"
    CHALLENGE = "CHALLENGE"
    HOLD = "HOLD"

    @property
    def is_detected(self) -> bool:
        return self in (VerdictStage.CHALLENGE, VerdictStage.HOLD)  # 탐지 = CHALLENGE 이상


class ActorType(str):
    """봇 유형 id · 기본 6종 = 아래 상수 · 화면에서 추가한 유형 = QA DB bot_types · 전체 목록은 macro_bots/bot_catalog"""
    __slots__ = ()

    HUMAN: "ActorType"
    BOT_A: "ActorType"
    BOT_B: "ActorType"
    BOT_C: "ActorType"
    BOT_D: "ActorType"
    BOT_NEW: "ActorType"  # 새 유형 · 목표 없음 · 결과만 공개

    @property
    def value(self) -> str:
        return str.__str__(self)

    @property
    def is_bot(self) -> bool:
        return self.value != HUMAN_ACTOR_ID

    def __repr__(self) -> str:
        return f"ActorType({self.value!r})"


HUMAN_ACTOR_ID = "HUMAN"
ActorType.HUMAN = ActorType(HUMAN_ACTOR_ID)
ActorType.BOT_A = ActorType("BOT_A")
ActorType.BOT_B = ActorType("BOT_B")
ActorType.BOT_C = ActorType("BOT_C")
ActorType.BOT_D = ActorType("BOT_D")
ActorType.BOT_NEW = ActorType("BOT_NEW")
BUILT_IN_ACTOR_TYPES: tuple[ActorType, ...] = (
    ActorType.HUMAN, ActorType.BOT_A, ActorType.BOT_B, ActorType.BOT_C, ActorType.BOT_D, ActorType.BOT_NEW,
)


class SessionStep(StrEnum):
    """B3 종류별 진행 · 가상 사용자 한 명이 지나가는 단계"""
    ENTERED = "ENTERED"
    SEAT_SELECTED = "SEAT_SELECTED"
    CONFIRMED = "CONFIRMED"
    VERDICT_RECEIVED = "VERDICT_RECEIVED"


class BookingOutcome(StrEnum):
    """VU 한 명의 예매 결과 · 오류는 VirtualUserSessionResult.is_error"""
    BOOKED = "BOOKED"
    SOLD_OUT = "SOLD_OUT"  # 남은 좌석 없음 · 오픈 경쟁의 정상 결과


class TargetKind(StrEnum):
    FAKE = "fake"
    LIVE = "live"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class SuiteOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # NotImplementedError · 실패 아님
    ERROR = "ERROR"


class Comparison(StrEnum):
    AT_MOST = "<="
    AT_LEAST = ">="


class AlertPolicy(StrEnum):
    NEVER = "never"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"
