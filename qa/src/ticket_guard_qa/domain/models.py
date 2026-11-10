"""시험 입력 · 결과의 데이터 모양"""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, NewType

from ticket_guard_qa.domain.enums import (
    ActorType,
    AlertPolicy,
    BookingOutcome,
    RunStatus,
    SuiteOutcome,
    TargetKind,
    VerdictStage,
)

SessionKey = NewType("SessionKey", str)  # 지금은 bookingAttemptId · AGENTS.md 11장
AnswerKey = dict[SessionKey, ActorType]
SystemVerdicts = dict[SessionKey, VerdictStage]
ActorProgress = dict[str, dict[str, int]]  # 종류 → {"PLANNED" · SessionStep 값: 사람 수} · B3


LEGACY_TRAFFIC_FIELD_TO_ACTOR = {  # 이전 Run 기록 · 이전 폼 이름 호환
    "human_percent": "HUMAN", "bot_a_percent": "BOT_A", "bot_b_percent": "BOT_B",
    "bot_c_percent": "BOT_C", "bot_d_percent": "BOT_D",
}
DEFAULT_TRAFFIC_PERCENTS = {"HUMAN": 80, "BOT_A": 5, "BOT_B": 5, "BOT_C": 5, "BOT_D": 5}


@dataclass(frozen=True)
class TrafficMix:
    """유형 id → 비율(%) · 봇 유형이 늘어도 구조 그대로 · 0% 유형은 저장 안 함"""
    percent_by_type: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_TRAFFIC_PERCENTS))

    def __post_init__(self) -> None:
        if any(percent < 0 for percent in self.percent_by_type.values()):
            raise ValueError("트래픽 구성 오류 · 음수 비율")
        if sum(self.percent_by_type.values()) != 100:
            raise ValueError("트래픽 구성 합계 오류 · 100% 필요")
        object.__setattr__(self, "percent_by_type", {key: value for key, value in self.percent_by_type.items() if value})

    def percent_by_actor_type(self) -> dict[ActorType, int]:
        return {ActorType(key): value for key, value in self.percent_by_type.items()}

    def percent_of(self, actor_type: ActorType | str) -> int:
        return self.percent_by_type.get(str(actor_type), 0)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrafficMix":
        if "percent_by_type" in raw:
            return cls(dict(raw["percent_by_type"]))
        return cls({LEGACY_TRAFFIC_FIELD_TO_ACTOR[name]: value for name, value in raw.items() if name in LEGACY_TRAFFIC_FIELD_TO_ACTOR})


@dataclass(frozen=True)
class RunConfig:
    target_kind: TargetKind
    suite_names: tuple[str, ...]
    virtual_user_count: int = 200
    duration_sec: int = 300  # Live = 트래픽 Suite 1개 최대 시간 · 0 = 자동(예상 시간 기준) · Mock = 영향 없음
    traffic_mix: TrafficMix = field(default_factory=TrafficMix)
    random_seed: int = 20261103
    is_open_burst: bool = True  # 오픈 시각에 한꺼번에 진입 · T1
    alert_policy: AlertPolicy = AlertPolicy.ON_FAILURE
    bot_version_numbers: dict[str, int] = field(default_factory=dict)  # 종류 → 봇 버전 · 실행 시작 때 채움


@dataclass(frozen=True)
class PlannedUser:
    virtual_user_label: str  # qa-0001 · 봇 여부를 드러내지 않음
    actor_type: ActorType


@dataclass(frozen=True)
class SessionBehavior:
    """시스템에 보내는 행동 값 · 사람 / 봇 여부는 담지 않음 · 화면 입력 칸은 macro_bots/behavior_fields.py"""
    entry_delay_after_open_ms: int
    entry_delay_deviation_ms: int
    click_interval_mean_ms: int
    click_interval_deviation_ms: int
    browse_page_count: int  # 예매 전 목록 · 상세 화면 조회 수 · 0 = 바로 예매
    page_dwell_mean_ms: int
    page_dwell_deviation_ms: int
    sessions_per_device: int
    sold_out_retry_count: int  # 먼저 팔린 좌석 → 다른 좌석 재시도 · 0 = 바로 포기
    sold_out_retry_delay_ms: int
    browser_trace_level: int  # 0 = API 요청만 · 1 = 화면 조회 · 화면 이벤트 · 브라우저 정보 전송


@dataclass(frozen=True)
class VirtualUserSessionPlan:
    """VU 한 명의 실행 계획 · 행동 값에서 뽑은 실제 대기 시간 · 사람 / 봇 여부는 담지 않음"""
    behavior: SessionBehavior
    entry_delay_ms: float  # 오픈(T0) → 예매 시작
    click_intervals_ms: tuple[float, ...]  # 좌석 클릭 간격 · 마지막 = 클릭 → 확정 · 재시도 때 반복 사용
    preferred_seat_ids: tuple[str, ...]  # 고를 좌석 순서 · 팔린 좌석은 건너뜀
    page_dwell_ms: tuple[float, ...] = ()  # 예매 전 화면마다 머무는 시간 · 길이 = 조회 화면 수
    device_key: str = ""  # 같은 값 = 같은 기기(쿠키 · 브라우저 정보 공유) · 봇 D 예매 창 묶음
    uses_browser: bool = False  # 브라우저 트래픽 유형(봇 C 등) · 실제 화면 열고 버튼 클릭


@dataclass(frozen=True)
class BrowserCaptureFrame:
    """브라우저 세션 한 단계 화면 · 클릭 위치는 화면 비율(0 ~ 1) · 이미지는 PNG 그대로"""
    step: str
    elapsed_ms: float  # 오픈(T0) 기준
    click_ratio_x: float | None
    click_ratio_y: float | None
    image_png: bytes | None = None


@dataclass(frozen=True)
class SessionVerdictRecord:
    """SESSION_VERDICTS 한 행 · docs/contracts.md 3-1"""
    booking_attempt_id: SessionKey
    stage: VerdictStage
    score: float
    matched_rules: tuple[str, ...]  # R1 ~ R6
    rule_set_version: str
    decided_at: datetime


@dataclass(frozen=True)
class SessionFeatureRecord:
    """SESSION_FEATURES 한 행 · 시스템이 계산한 세션 행동 값 · SessionBehavior와 1:1 대조"""
    booking_attempt_id: SessionKey
    entry_delay_after_open_ms: float
    click_interval_mean_ms: float
    click_interval_std_ms: float
    sessions_per_device: int
    event_count: int
    window_start: datetime
    window_end: datetime
    computed_at: datetime  # Gold 반영 시각


# 봇 파라미터 → SESSION_FEATURES 필드 · 집계 정확도 대조 · None = 세션 하나로는 계산 불가(세션 분포로 대조)
FEATURE_FIELD_BY_BEHAVIOR_FIELD: dict[str, str | None] = {
    "entry_delay_after_open_ms": "entry_delay_after_open_ms",
    "entry_delay_deviation_ms": None,
    "click_interval_mean_ms": "click_interval_mean_ms",
    "click_interval_deviation_ms": "click_interval_std_ms",
    "browse_page_count": None,
    "page_dwell_mean_ms": None,
    "page_dwell_deviation_ms": None,
    "sessions_per_device": "sessions_per_device",
    "sold_out_retry_count": None,
    "sold_out_retry_delay_ms": None,
    "browser_trace_level": None,
}


@dataclass(frozen=True)
class QuarantineRecord:
    """QUARANTINE_EVENTS 한 행 · 사유 코드는 docs/contracts.md 3-4"""
    raw_event_id: str
    stage: str
    reason_code: str
    quarantined_at: datetime


@dataclass(frozen=True)
class VirtualUserSessionResult:
    session_key: SessionKey
    latency_ms: float
    is_error: bool
    step_latency_ms: dict[str, float] = field(default_factory=dict)  # Live만 · login · start · queue · captcha · seat_select · confirm
    failed_step: str | None = None  # 예: "verify · CAPTCHA_WRONG"
    booking_outcome: BookingOutcome | None = None  # 오류면 None
    booked_seat_ids: tuple[str, ...] = ()  # 중복 판매 확인
    sent_event_ids: tuple[str, ...] = ()  # VU가 직접 보낸 브라우저 이벤트 · 이벤트 전달 검증 대조
    device_key: str = ""  # 계획의 기기 묶음 그대로 · 같은 기기 세션 대조
    capture_frames: tuple["BrowserCaptureFrame", ...] = ()  # 브라우저 세션 단계별 화면 · B3


@dataclass(frozen=True)
class LiveMetrics:
    """03 화면 실시간 수치 · 합격 기준 metric_name과 같은 이름"""
    api_latency_p95_sec: float
    api_error_rate_percent: float
    events_per_sec: float
    gold_latency_p95_sec: float


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    measured_value: float | None  # None = 이번 실행에서 측정 안 됨
    is_passed: bool | None


MESSAGE_LINE_SEPARATOR = "\n"  # Suite 메시지 · 한 줄 = 한 항목 · 04 화면 목록
FAIL_LINE_PREFIX = "FAIL: "
REFERENCE_LINE_PREFIX = "참고: "


@dataclass
class SuiteResult:
    suite_name: str
    outcome: SuiteOutcome
    metrics: dict[str, float] = field(default_factory=dict)
    message: str = ""  # 여러 항목은 MESSAGE_LINE_SEPARATOR로 구분
    details: dict[str, Any] = field(default_factory=dict)  # 화면용 · 놓친 세션 · 정답 × 판정 표
    duration_sec: float | None = None  # 실제 소요 · 다음 Run 예상 시간 보정 · 이전 기록 = None


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

    @property
    def failed_criteria_count(self) -> int:
        return sum(1 for result in self.criterion_results if result.is_passed is False)

    @property
    def measured_criteria_count(self) -> int:
        return sum(1 for result in self.criterion_results if result.is_passed is not None)

    @property
    def failed_suite_count(self) -> int:
        return sum(1 for result in self.suite_results if result.outcome in (SuiteOutcome.FAILED, SuiteOutcome.ERROR))

    @property
    def passed_suite_count(self) -> int:
        return sum(1 for result in self.suite_results if result.outcome is SuiteOutcome.PASSED)

    def find_suite_result(self, suite_name: str) -> SuiteResult | None:
        return next((result for result in self.suite_results if result.suite_name == suite_name), None)

    def measured_value_by_criterion_id(self) -> dict[str, float]:
        return {
            result.criterion_id: result.measured_value
            for result in self.criterion_results
            if result.measured_value is not None
        }


def run_config_to_dict(run_config: RunConfig) -> dict[str, Any]:
    raw = asdict(run_config)
    raw["target_kind"] = run_config.target_kind.value
    raw["suite_names"] = list(run_config.suite_names)
    raw["alert_policy"] = run_config.alert_policy.value
    return raw


def run_config_from_dict(raw: dict[str, Any]) -> RunConfig:
    return RunConfig(
        target_kind=TargetKind(raw["target_kind"]),
        suite_names=tuple(raw["suite_names"]),
        virtual_user_count=raw["virtual_user_count"],
        duration_sec=raw["duration_sec"],
        traffic_mix=TrafficMix.from_dict(raw["traffic_mix"]),
        random_seed=raw["random_seed"],
        is_open_burst=raw.get("is_open_burst", True),  # 이전 기록 호환
        alert_policy=AlertPolicy(raw.get("alert_policy", AlertPolicy.ON_FAILURE.value)),
        bot_version_numbers=raw.get("bot_version_numbers", {}),
    )


def verdicts_from_records(records: list[SessionVerdictRecord]) -> SystemVerdicts:
    return {record.booking_attempt_id: record.stage for record in records}
