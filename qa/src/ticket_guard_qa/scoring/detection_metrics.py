"""탐지율 · 오탐률 · 놓친 봇 · 오탐 세션"""
from collections.abc import Iterable

from ticket_guard_qa.domain.detection_targets import DETECTION_TARGETS
from ticket_guard_qa.domain.enums import ActorType, VerdictStage
from ticket_guard_qa.domain.models import AnswerKey, SessionKey, SystemVerdicts


def _is_detected(session_key: SessionKey, system_verdicts: SystemVerdicts) -> bool:
    verdict_stage = system_verdicts.get(session_key, VerdictStage.NORMAL)  # 판정 없음 = 놓침
    return verdict_stage.is_detected


def calculate_detection_rate_percent(
    answer_key: AnswerKey, system_verdicts: SystemVerdicts, actor_types: Iterable[ActorType]
) -> float | None:
    target_types = set(actor_types)
    bot_sessions = [key for key, actor_type in answer_key.items() if actor_type in target_types]
    if not bot_sessions:
        return None
    detected_count = sum(1 for key in bot_sessions if _is_detected(key, system_verdicts))
    return detected_count / len(bot_sessions) * 100


def calculate_false_positive_rate_percent(answer_key: AnswerKey, system_verdicts: SystemVerdicts) -> float | None:
    human_sessions = [key for key, actor_type in answer_key.items() if actor_type is ActorType.HUMAN]
    if not human_sessions:
        return None
    false_positive_count = sum(1 for key in human_sessions if _is_detected(key, system_verdicts))
    return false_positive_count / len(human_sessions) * 100


def find_missed_bots(answer_key: AnswerKey, system_verdicts: SystemVerdicts) -> list[SessionKey]:
    return [
        key for key, actor_type in answer_key.items()
        if actor_type.is_bot and not _is_detected(key, system_verdicts)
    ]


def find_false_positives(answer_key: AnswerKey, system_verdicts: SystemVerdicts) -> list[SessionKey]:
    return [
        key for key, actor_type in answer_key.items()
        if actor_type is ActorType.HUMAN and _is_detected(key, system_verdicts)
    ]


def calculate_detection_metrics(answer_key: AnswerKey, system_verdicts: SystemVerdicts) -> dict[str, float]:
    """합격 기준 metric_name 그대로 반환 · 측정 안 된 값은 빠짐 · 묶음은 domain/detection_targets.py"""
    candidates = {
        target.criterion.metric_name: calculate_detection_rate_percent(answer_key, system_verdicts, target.actor_types)
        for target in DETECTION_TARGETS
    }
    return {name: value for name, value in candidates.items() if value is not None}
