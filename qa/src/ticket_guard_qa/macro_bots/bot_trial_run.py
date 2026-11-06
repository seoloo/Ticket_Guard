"""B2 모의 판정 · 저장 전 행동 값을 가짜 대상에 몇 세션 보내 판정 분포 확인 · 정답표 저장 안 함"""
from dataclasses import dataclass

from ticket_guard_qa.domain.enums import VerdictStage
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.system_targets.target_interfaces import SystemTarget
from ticket_guard_qa.traffic_generators.virtual_user_traffic import build_session_plans, send_virtual_user_traffic

TRIAL_SESSION_COUNT = 20  # 1세션은 운에 따라 결과가 갈려서 여러 번
TRIAL_RUN_ID = "bot-trial"
TRIAL_RANDOM_SEED = 0
TRIAL_TIME_LIMIT_SEC = 30.0


@dataclass(frozen=True)
class TrialRunResult:
    session_count: int
    count_by_stage: dict[VerdictStage, int]

    @property
    def detected_count(self) -> int:
        return sum(count for stage, count in self.count_by_stage.items() if stage.is_detected)

    @property
    def detection_rate_percent(self) -> float:
        return self.detected_count / self.session_count * 100 if self.session_count else 0.0


def run_trial_sessions(
    system_target: SystemTarget, behavior: SessionBehavior, session_count: int = TRIAL_SESSION_COUNT
) -> TrialRunResult:
    session_plans = build_session_plans([behavior] * session_count, TRIAL_RANDOM_SEED)
    session_results = send_virtual_user_traffic(system_target.booking_api, session_plans, TRIAL_TIME_LIMIT_SEC)
    session_keys = [result.session_key for result in session_results]
    verdicts = system_target.verdict_reader.read_session_verdicts(TRIAL_RUN_ID)
    count_by_stage = {stage: 0 for stage in VerdictStage}
    for session_key in session_keys:
        count_by_stage[verdicts.get(session_key, VerdictStage.NORMAL)] += 1  # 판정 없음 = NORMAL
    return TrialRunResult(session_count, count_by_stage)
