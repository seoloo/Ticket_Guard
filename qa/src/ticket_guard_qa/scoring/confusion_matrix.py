"""정답 × 판정 표 · B4 화면"""
from ticket_guard_qa.domain.enums import ActorType, VerdictStage
from ticket_guard_qa.domain.models import AnswerKey, SystemVerdicts

ConfusionMatrix = dict[ActorType, dict[VerdictStage, int]]


def build_confusion_matrix(answer_key: AnswerKey, system_verdicts: SystemVerdicts) -> ConfusionMatrix:
    matrix: ConfusionMatrix = {
        actor_type: {verdict_stage: 0 for verdict_stage in VerdictStage} for actor_type in ActorType
    }
    for session_key, actor_type in answer_key.items():
        verdict_stage = system_verdicts.get(session_key, VerdictStage.NORMAL)  # 판정 없음 = NORMAL 칸
        matrix[actor_type][verdict_stage] += 1
    return matrix
