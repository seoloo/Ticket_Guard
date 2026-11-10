"""Live Run 예상 소요 시간 · Suite별 합계 · 최근 Live Run 실측이 있으면 실측 · 없으면 계산
트래픽 Suite 최대 시간(자동) = 트래픽 Suite 예상 × 여유 배수 · 02 Run 요약 · 03 남은 시간"""
import math
from collections import Counter
from dataclasses import dataclass
from statistics import median

from ticket_guard_qa.answer_key.expected_verdicts import plan_virtual_users
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.macro_bots.bot_catalog import BROWSER_TRAFFIC, get_bot_type_info
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry
from ticket_guard_qa.system_targets.live_django_system import MAX_CONCURRENT_BROWSERS
from ticket_guard_qa.test_suites.booking_flow import BOOKING_FLOW_SUITE_NAME
from ticket_guard_qa.test_suites.event_delivery import EVENT_DELIVERY_SUITE_NAME
from ticket_guard_qa.test_suites.verdict_accuracy import VERDICT_ACCURACY_SUITE_NAME
from ticket_guard_qa.traffic_generators.virtual_user_traffic import PRE_OPEN_LOGIN_SEC

TRAFFIC_SUITE_NAMES = (BOOKING_FLOW_SUITE_NAME, EVENT_DELIVERY_SUITE_NAME, VERDICT_ACCURACY_SUITE_NAME)  # VU 전원 트래픽
DEFAULT_SUITE_SEC = {  # 트래픽 없는 Suite · 실측 전 초기값
    "self_check": 2.0, "event_contract": 15.0, "raw_ingest": 10.0, "pipeline_latency": 10.0,
    "seat_concurrency": 20.0, "load_capacity": 90.0, "failure_recovery": 60.0,
}
UNKNOWN_SUITE_SEC = 30.0
ASSUMED_ADMISSION_LIMIT = 25  # 시스템 동시 입장 상한 모를 때 · 지난 Live Run 최대 동시 입장 25 ~ 31
QUEUE_WAIT_SEC = 12.0  # 시스템 기본 대기열 대기
HTTP_ADMITTED_SEC = 6.0  # 입장 뒤 보안문자 → 좌석 → 확정 · HTTP VU 1명
BROWSER_SESSION_SEC = 35.0  # 브라우저 VU 1명 · 로그인 → 확정 · 실측 30 ~ 40초
AUTO_TIME_LIMIT_FACTOR = 2.0  # 자동 최대 시간 = 트래픽 Suite 예상 × 2
MIN_AUTO_TIME_LIMIT_SEC, MAX_AUTO_TIME_LIMIT_SEC = 120, 900
HISTORY_RUN_LIMIT = 5  # 최근 Live Run 수
RANGE_LOW_FACTOR, RANGE_HIGH_FACTOR = 0.8, 1.3
ESTIMATE_FROM_HISTORY, ESTIMATE_FROM_FORMULA = "recent", "formula"
SuiteDurationSample = tuple[str, int, float]  # (Suite 이름, VU 수, 실제 소요 초)


@dataclass(frozen=True)
class SuiteEstimate:
    suite_name: str
    seconds: float
    source: str  # recent = 최근 Live Run 실측 · formula = 계산


@dataclass(frozen=True)
class RunEstimate:
    suites: tuple[SuiteEstimate, ...]
    traffic_time_limit_sec: int  # 트래픽 Suite 1개 최대 시간 · 넘으면 남은 VU 시간 초과
    is_time_limit_auto: bool

    @property
    def total_sec(self) -> float:
        return sum(suite.seconds for suite in self.suites)

    @property
    def low_sec(self) -> float:
        return self.total_sec * RANGE_LOW_FACTOR

    @property
    def high_sec(self) -> float:
        return self.total_sec * RANGE_HIGH_FACTOR

    def to_payload(self) -> dict:
        return {
            "total_sec": round(self.total_sec), "low_sec": round(self.low_sec), "high_sec": round(self.high_sec),
            "traffic_time_limit_sec": self.traffic_time_limit_sec, "is_time_limit_auto": self.is_time_limit_auto,
            "suites": [{"suite_name": suite.suite_name, "seconds": round(suite.seconds), "source": suite.source}
                       for suite in self.suites],
        }


def calculate_traffic_suite_sec(run_config: RunConfig, registry: BotProfileRegistry, admission_limit: int) -> float:
    """오픈 전 준비 + max(대기열 처리, 브라우저 차례 대기) · 같은 기기 창은 브라우저 1개"""
    planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)
    count_by_actor = Counter(user.actor_type for user in planned_users)
    behavior_by_actor = {actor: registry.get_profile(actor).behavior for actor in count_by_actor}
    longest_browse_sec = max((behavior.browse_page_count * behavior.page_dwell_mean_ms / 1000
                              for behavior in behavior_by_actor.values()), default=0.0)
    pre_open_sec = PRE_OPEN_LOGIN_SEC + longest_browse_sec
    queue_sec = QUEUE_WAIT_SEC + math.ceil(len(planned_users) / max(admission_limit, 1)) * HTTP_ADMITTED_SEC
    browser_count = sum(
        math.ceil(count / max(behavior_by_actor[actor].sessions_per_device, 1))
        for actor, count in count_by_actor.items() if get_bot_type_info(actor).traffic_channel == BROWSER_TRAFFIC
    )
    browser_sec = math.ceil(browser_count / MAX_CONCURRENT_BROWSERS) * BROWSER_SESSION_SEC if browser_count else 0.0
    return pre_open_sec + max(queue_sec, browser_sec)


def estimate_from_history(suite_name: str, virtual_user_count: int, samples: list[SuiteDurationSample]) -> float | None:
    """같은 Suite 최근 실측 중앙값 · 트래픽 Suite는 VU 수 비율로 환산"""
    durations = [
        duration * (virtual_user_count / sample_users if suite_name in TRAFFIC_SUITE_NAMES and sample_users else 1.0)
        for name, sample_users, duration in samples if name == suite_name
    ]
    return median(durations) if durations else None


def decide_traffic_time_limit(run_config: RunConfig, traffic_suite_sec: float) -> tuple[int, bool]:
    if run_config.duration_sec > 0:
        return run_config.duration_sec, False
    auto_sec = math.ceil(traffic_suite_sec * AUTO_TIME_LIMIT_FACTOR)
    return min(max(auto_sec, MIN_AUTO_TIME_LIMIT_SEC), MAX_AUTO_TIME_LIMIT_SEC), True


def estimate_live_run(
    run_config: RunConfig, registry: BotProfileRegistry, admission_limit: int, samples: list[SuiteDurationSample],
) -> RunEstimate:
    admission_limit = admission_limit or ASSUMED_ADMISSION_LIMIT
    formula_traffic_sec = calculate_traffic_suite_sec(run_config, registry, admission_limit)
    time_limit_sec, is_auto = decide_traffic_time_limit(run_config, formula_traffic_sec)
    estimates = []
    for suite_name in run_config.suite_names:
        recent_sec = estimate_from_history(suite_name, run_config.virtual_user_count, samples)
        if recent_sec is not None:
            seconds, source = recent_sec, ESTIMATE_FROM_HISTORY
        elif suite_name in TRAFFIC_SUITE_NAMES:
            seconds, source = formula_traffic_sec, ESTIMATE_FROM_FORMULA
        else:
            seconds, source = DEFAULT_SUITE_SEC.get(suite_name, UNKNOWN_SUITE_SEC), ESTIMATE_FROM_FORMULA
        if suite_name in TRAFFIC_SUITE_NAMES:
            seconds = min(seconds, time_limit_sec + PRE_OPEN_LOGIN_SEC)  # 최대 시간 넘으면 남은 VU 시간 초과로 끝남
        estimates.append(SuiteEstimate(suite_name, seconds, source))
    return RunEstimate(tuple(estimates), time_limit_sec, is_auto)
