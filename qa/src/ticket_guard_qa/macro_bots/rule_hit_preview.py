"""R1 ~ R6 예상 결과 · B2 오른쪽 패널 · 규칙이 정해지면 RULE_CHECKS에 조건만 추가"""
from collections.abc import Callable
from dataclasses import dataclass

from ticket_guard_qa.domain.models import SessionBehavior

RULE_IDS: tuple[str, ...] = ("R1", "R2", "R3", "R4", "R5", "R6")
RULE_PENDING_REASON = "판정 규칙 확정 대기"

RuleCheck = Callable[[SessionBehavior], tuple[bool, str]]  # (걸리나, 이유)

# TODO(판정 규칙 확정 후): "R1": lambda behavior: (behavior.click_interval_mean_ms < 200, "클릭 간격 200ms 미만") 형태로 추가
RULE_CHECKS: dict[str, RuleCheck] = {}


@dataclass(frozen=True)
class RuleHitPreview:
    rule_id: str
    is_expected_hit: bool | None  # None = 규칙 아직 없음
    reason: str


def predict_rule_hits(behavior: SessionBehavior) -> list[RuleHitPreview]:
    previews = []
    for rule_id in RULE_IDS:
        rule_check = RULE_CHECKS.get(rule_id)
        if rule_check is None:
            previews.append(RuleHitPreview(rule_id, None, RULE_PENDING_REASON))
            continue
        is_hit, reason = rule_check(behavior)
        previews.append(RuleHitPreview(rule_id, is_hit, reason))
    return previews
