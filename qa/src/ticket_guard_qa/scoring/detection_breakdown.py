"""종류별 탐지율 · 목표 대비 · B1 카드 · B4 표 · 저장된 정답 × 판정 표에서 계산"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ticket_guard_qa.domain.detection_targets import DetectionTarget, find_detection_target
from ticket_guard_qa.domain.enums import ActorType, VerdictStage
from ticket_guard_qa.domain.models import SessionVerdictRecord
from ticket_guard_qa.scoring.confusion_matrix import ConfusionMatrix


class VerdictOutcome(StrEnum):
    """정답 × 판정 한 칸의 뜻 · B4 칸 색"""
    CAUGHT = "CAUGHT"  # 봇 · 탐지
    MISSED = "MISSED"  # 봇 · 놓침
    FALSE_POSITIVE = "FALSE_POSITIVE"  # 사람 · 탐지
    CORRECT_PASS = "CORRECT_PASS"  # 사람 · 통과


def classify_verdict(actor_type: ActorType, verdict_stage: VerdictStage) -> VerdictOutcome:
    if actor_type.is_bot:
        return VerdictOutcome.CAUGHT if verdict_stage.is_detected else VerdictOutcome.MISSED
    return VerdictOutcome.FALSE_POSITIVE if verdict_stage.is_detected else VerdictOutcome.CORRECT_PASS


@dataclass(frozen=True)
class ActorDetectionRow:
    actor_type: ActorType
    count_by_stage: dict[VerdictStage, int]

    @property
    def session_count(self) -> int:
        return sum(self.count_by_stage.values())

    @property
    def detected_count(self) -> int:
        return sum(count for stage, count in self.count_by_stage.items() if stage.is_detected)

    @property
    def detection_rate_percent(self) -> float | None:
        return self.detected_count / self.session_count * 100 if self.session_count else None

    @property
    def target(self) -> DetectionTarget | None:
        return find_detection_target(self.actor_type)

    @property
    def is_meeting_target(self) -> bool | None:
        """None = 목표 없음 · 세션 없음 · 종류 하나씩 본 값이라 묶음 합격과 다를 수 있음"""
        rate = self.detection_rate_percent
        if self.target is None or rate is None:
            return None
        return self.target.criterion.is_met_by(rate)


def count_rule_hits(verdict_records: list[SessionVerdictRecord]) -> dict[str, int]:
    """B4 룰별 Hit 수 · 탐지(CHALLENGE 이상)된 세션에서 걸린 룰만 · 룰 이름 순"""
    hit_count_by_rule_id: dict[str, int] = {}
    for record in verdict_records:
        if not record.stage.is_detected:
            continue
        for rule_id in record.matched_rules:
            hit_count_by_rule_id[rule_id] = hit_count_by_rule_id.get(rule_id, 0) + 1
    return dict(sorted(hit_count_by_rule_id.items()))


def confusion_matrix_from_details(raw_matrix: dict[str, dict[str, int]]) -> ConfusionMatrix:
    """suite_results.details JSON → 표 · 저장 뒤 생긴 종류 · 단계는 0으로 채움"""
    return {
        actor_type: {stage: raw_matrix.get(actor_type.value, {}).get(stage.value, 0) for stage in VerdictStage}
        for actor_type in ActorType
    }


def build_actor_detection_rows(confusion_matrix: ConfusionMatrix) -> list[ActorDetectionRow]:
    return [ActorDetectionRow(actor_type, dict(row)) for actor_type, row in confusion_matrix.items()]


def build_actor_detection_rows_from_details(verdict_details: dict[str, Any]) -> dict[ActorType, ActorDetectionRow]:
    matrix = confusion_matrix_from_details(verdict_details.get("confusion_matrix", {}))
    return {row.actor_type: row for row in build_actor_detection_rows(matrix)}
