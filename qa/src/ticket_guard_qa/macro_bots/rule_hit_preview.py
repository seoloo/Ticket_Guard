"""룰 매칭 예측 · B2 오른쪽 패널 · 규칙 정의는 domain/rule_sets.py · 없는 룰셋 버전 = R1 ~ R6 대기"""
from dataclasses import dataclass

from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.domain.rule_sets import RULE_SETS

PENDING_RULE_IDS: tuple[str, ...] = ("R1", "R2", "R3", "R4", "R5", "R6")
RULE_PENDING_REASON = "룰셋 미정"


@dataclass(frozen=True)
class RuleHitPreview:
    rule_id: str
    is_expected_hit: bool | None  # None = 규칙 아직 없음
    reason: str


def predict_rule_hits(behavior: SessionBehavior, rule_set_version: str) -> list[RuleHitPreview]:
    rules = RULE_SETS.get(rule_set_version)
    if rules is None:
        return [RuleHitPreview(rule_id, None, RULE_PENDING_REASON) for rule_id in PENDING_RULE_IDS]
    return [RuleHitPreview(rule.rule_id, rule.is_matched(behavior), rule.condition) for rule in rules]
