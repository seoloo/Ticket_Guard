"""시험 입력 · 결과의 데이터 모양"""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, NewType

from ticket_guard_qa.domain.enums import ActorType, RunStatus, SuiteOutcome, TargetKind, VerdictStage

SessionKey = NewType("SessionKey", str)  # 지금은 bookingAttemptId · AGENTS.md 11장
AnswerKey = dict[SessionKey, ActorType]
SystemVerdicts = dict[SessionKey, VerdictStage]


@dataclass(frozen=True)
class TrafficMix:
    human_percent: int = 80
    bot_a_percent: int = 5
    bot_b_percent: int = 5
    bot_c_percent: int = 5
    bot_d_percent: int = 5

    def __post_init__(self) -> None:
        if sum(self.percent_by_actor_type().values()) != 100:
            raise ValueError("트래픽 구성 합계는 100이어야 해요.")

    def percent_by_actor_type(self) -> dict[ActorType, int]:
        return {
            ActorType.HUMAN: self.human_percent,
            ActorType.BOT_A: self.bot_a_percent,
            ActorType.BOT_B: self.bot_b_percent,
            ActorType.BOT_C: self.bot_c_percent,
            ActorType.BOT_D: self.bot_d_percent,
        }


@dataclass(frozen=True)
class RunConfig:
    target_kind: TargetKind
    suite_names: tuple[str, ...]
    virtual_user_count: int = 200
    duration_sec: int = 300
    traffic_mix: TrafficMix = field(default_factory=TrafficMix)
    random_seed: int = 20261103


@dataclass(frozen=True)
class PlannedUser:
    virtual_user_label: str  # qa-0001 · 봇 여부를 드러내지 않음
    actor_type: ActorType


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    measured_value: float | None  # None = 이번 실행에서 측정 안 됨
    is_passed: bool | None


@dataclass
class SuiteResult:
    suite_name: str
    outcome: SuiteOutcome
    metrics: dict[str, float] = field(default_factory=dict)
    message: str = ""


@dataclass
class RunSummary:
    run_id: str
    run_config: RunConfig
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    suite_results: list[SuiteResult] = field(default_factory=list)
    criterion_results: list[CriterionResult] = field(default_factory=list)

    @property
    def passed_criteria_count(self) -> int:
        return sum(1 for result in self.criterion_results if result.is_passed)


def run_config_to_dict(run_config: RunConfig) -> dict[str, Any]:
    raw = asdict(run_config)
    raw["target_kind"] = run_config.target_kind.value
    raw["suite_names"] = list(run_config.suite_names)
    return raw


def run_config_from_dict(raw: dict[str, Any]) -> RunConfig:
    return RunConfig(
        target_kind=TargetKind(raw["target_kind"]),
        suite_names=tuple(raw["suite_names"]),
        virtual_user_count=raw["virtual_user_count"],
        duration_sec=raw["duration_sec"],
        traffic_mix=TrafficMix(**raw["traffic_mix"]),
        random_seed=raw["random_seed"],
    )
