"""판정 규칙 정의 한 곳 · B2 룰 매칭 예측 · 가짜 판정이 같이 사용 · 실제 규칙 확정 시 RULE_SETS에 버전 추가"""
from collections.abc import Callable
from dataclasses import dataclass

from ticket_guard_qa.domain.models import SessionBehavior


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    condition: str  # 화면 표시 · 걸리는 조건
    is_matched: Callable[[SessionBehavior], bool]


MOCK_RULE_SET_VERSION = "mock-1"  # 가짜 규칙 · 실제 R1 ~ R6와 무관
REGULAR_CLICK_DEVIATION_RATIO = 0.3
FAST_CLICK_INTERVAL_MS = 200
INSTANT_ENTRY_DELAY_MS = 100
MULTI_SESSION_DEVICE_COUNT = 2

MOCK_RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition("MOCK-R1", "클릭 간격 편차 < 평균의 30%",
                   lambda behavior: behavior.click_interval_deviation_ms < behavior.click_interval_mean_ms * REGULAR_CLICK_DEVIATION_RATIO),
    RuleDefinition("MOCK-R2", "클릭 간격 평균 < 200ms",
                   lambda behavior: behavior.click_interval_mean_ms < FAST_CLICK_INTERVAL_MS),
    RuleDefinition("MOCK-R3", "기기당 세션 > 2",
                   lambda behavior: behavior.sessions_per_device > MULTI_SESSION_DEVICE_COUNT),
    RuleDefinition("MOCK-R4", "오픈 후 진입 < 100ms",
                   lambda behavior: behavior.entry_delay_after_open_ms < INSTANT_ENTRY_DELAY_MS),
)

RULE_SETS: dict[str, tuple[RuleDefinition, ...]] = {MOCK_RULE_SET_VERSION: MOCK_RULES}


def find_matched_rule_ids(behavior: SessionBehavior, rule_set_version: str = MOCK_RULE_SET_VERSION) -> tuple[str, ...]:
    return tuple(rule.rule_id for rule in RULE_SETS.get(rule_set_version, ()) if rule.is_matched(behavior))
