"""탐지 목표 · 어떤 종류를 묶어 어떤 합격 기준으로 보나 · 점수 계산 · B1 · B4가 같이 씀 · 기획서 21쪽"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERION_BY_ID, PassCriterion


@dataclass(frozen=True)
class DetectionTarget:
    """묶음 안 세션 중 CHALLENGE 이상 비율 → 합격 기준 값 · 사람은 이 비율이 곧 오탐률"""
    criterion_id: str
    actor_types: tuple[ActorType, ...]

    @property
    def criterion(self) -> PassCriterion:
        return PASS_CRITERION_BY_ID[self.criterion_id]


# 새 봇 목표는 여기 한 줄 + pass_criteria.py 기준 한 줄 · 새 유형(BOT_NEW)은 목표 없음
DETECTION_TARGETS: tuple[DetectionTarget, ...] = (
    DetectionTarget("bot_abd_detection", (ActorType.BOT_A, ActorType.BOT_B, ActorType.BOT_D)),
    DetectionTarget("bot_c_detection", (ActorType.BOT_C,)),
    DetectionTarget("human_false_positive", (ActorType.HUMAN,)),
)


def find_detection_target(actor_type: ActorType) -> DetectionTarget | None:
    return next((target for target in DETECTION_TARGETS if actor_type in target.actor_types), None)
