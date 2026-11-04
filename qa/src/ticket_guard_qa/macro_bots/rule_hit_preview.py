"""R1 ~ R6 예상 결과 · B2 오른쪽 패널"""
from dataclasses import dataclass

from ticket_guard_qa.macro_bots.bot_profiles import BotProfile


@dataclass(frozen=True)
class RuleHitPreview:
    rule_id: str  # R1 ~ R6
    is_expected_hit: bool
    reason: str


def predict_rule_hits(profile: BotProfile) -> list[RuleHitPreview]:
    # TODO(판정 규칙 확정 후): R1 ~ R6 조건을 프로필 값에 대 보기
    raise NotImplementedError("판정 규칙 R1 ~ R6 정의 대기")
