"""탐지 목표 · 어떤 종류를 묶어 어떤 합격 기준으로 보나 · 점수 계산 · B1 · B4가 같이 씀 · 기획서 21쪽"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERION_BY_ID, PassCriterion


@dataclass(frozen=True)
class DetectionTarget:
    """묶음 안 세션 중 CHALLENGE 이상 비율 → 합격 기준 값 · 사람은 이 비율이 곧 오탐률"""
    criterion_id: str
    title: str  # 새 봇 추가 4단계 선택지

    @property
    def criterion(self) -> PassCriterion:
        return PASS_CRITERION_BY_ID[self.criterion_id]

    @property
    def actor_types(self) -> tuple[ActorType, ...]:
        """묶음 소속 = 봇 유형마다 정한 detection_target_id · 화면에서 추가한 유형 포함"""
        from ticket_guard_qa.macro_bots.bot_catalog import list_bot_types  # 순환 import 방지

        return tuple(info.actor_type for info in list_bot_types()
                     if info.detection_target_id == self.criterion_id and info.status.is_in_runs)  # 작성 중 제외


# 새 묶음은 여기 한 줄 + pass_criteria.py 기준 한 줄 · 소속은 bot_catalog의 detection_target_id
DETECTION_TARGETS: tuple[DetectionTarget, ...] = (
    DetectionTarget("bot_abd_detection", "매크로 탐지율 · 90% 이상 · 봇 A · B · D와 합산"),
    DetectionTarget("bot_c_detection", "브라우저 자동화 탐지율 · 70% 이상 · 봇 C와 합산"),
    DetectionTarget("human_false_positive", "정상 사용자 오탐률"),
)
DETECTION_TARGET_BY_ID = {target.criterion_id: target for target in DETECTION_TARGETS}
BOT_SELECTABLE_TARGET_IDS = {"bot_abd_detection", "bot_c_detection"}  # 새 봇이 고를 수 있는 묶음


def find_detection_target(actor_type: ActorType) -> DetectionTarget | None:
    from ticket_guard_qa.macro_bots.bot_catalog import find_bot_type_info  # 순환 import 방지

    info = find_bot_type_info(actor_type)
    return DETECTION_TARGET_BY_ID.get(info.detection_target_id) if info and info.detection_target_id else None
