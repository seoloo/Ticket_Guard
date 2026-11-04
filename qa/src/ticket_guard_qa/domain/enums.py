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


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    BOT_A = "BOT_A"
    BOT_B = "BOT_B"
    BOT_C = "BOT_C"
    BOT_D = "BOT_D"
    BOT_NEW = "BOT_NEW"  # 새 유형 · 목표 없음 · 결과만 공개

    @property
    def is_bot(self) -> bool:
        return self is not ActorType.HUMAN


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


class AdminCheckMode(StrEnum):
    LOCAL_ONLY = "local_only"  # 혼자 개발 · 127.0.0.1 직접 접속만
    GATEWAY_HEADER = "gateway_header"  # 팀 입구(nginx)가 붙인 X-Admin-User만
