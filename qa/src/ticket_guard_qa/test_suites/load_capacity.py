"""부하 · T1 동시 입장 상한 · T2 요청 속도 제한 · 오픈 동시 진입 시 서버 오류 0"""
import asyncio
from dataclasses import dataclass, field

from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, REFERENCE_LINE_PREFIX, SuiteResult
from ticket_guard_qa.scoring.latency_metrics import calculate_p95
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError, AdmissionSample, BookingApi
from ticket_guard_qa.test_suites.suite_interface import SuiteContext
from ticket_guard_qa.traffic_generators.virtual_user_traffic import reset_before_traffic

LOAD_SHOW_ID = "blue-hour"
ADMISSION_HOLD_SEC = 1.0  # 입장 후 머무는 시간 · 동시 입장 구간 겹침 측정
BURST_REQUEST_COUNT = 30  # T2 · 간격 없이 연속
NORMAL_REQUEST_COUNT = 5  # T2 · 사람 속도 · 제한되면 안 됨
NORMAL_REQUEST_INTERVAL_SEC = 0.5
RATE_LIMITED_STATUS_CODE = 429
SERVER_ERROR_STATUS_CODE = 500
CONNECTION_ERROR_STATUS_CODE = 0
MIN_VIRTUAL_USER_COUNT = 2
MAX_LISTED_ERROR_COUNT = 3


@dataclass
class LoadReport:
    virtual_user_count: int
    samples: list[AdmissionSample] = field(default_factory=list)
    burst_status_codes: list[int] = field(default_factory=list)
    normal_status_codes: list[int] = field(default_factory=list)

    @property
    def admitted_samples(self) -> list[AdmissionSample]:
        return [sample for sample in self.samples if sample.admitted_at_sec is not None]

    @property
    def admission_errors(self) -> list[str]:
        return [sample.error or "입장 실패" for sample in self.samples if sample.admitted_at_sec is None]

    @property
    def peak_concurrent_admissions(self) -> int:
        return calculate_peak_concurrency(self.admitted_samples)

    @property
    def is_admission_limited(self) -> bool:  # T1
        return bool(self.admitted_samples) and self.peak_concurrent_admissions < self.virtual_user_count

    @property
    def is_burst_limited(self) -> bool:  # T2 · 연속 요청 차단
        return RATE_LIMITED_STATUS_CODE in self.burst_status_codes

    @property
    def is_normal_rate_blocked(self) -> bool:  # T2 · 사람 속도 오차단
        return RATE_LIMITED_STATUS_CODE in self.normal_status_codes

    @property
    def server_error_count(self) -> int:
        status_codes = self.burst_status_codes + self.normal_status_codes
        return len(self.admission_errors) + sum(
            code == CONNECTION_ERROR_STATUS_CODE or code >= SERVER_ERROR_STATUS_CODE for code in status_codes
        )


def calculate_peak_concurrency(samples: list[AdmissionSample]) -> int:
    """입장 → 이탈 구간이 가장 많이 겹친 수 · 같은 시각이면 이탈 먼저"""
    boundaries = sorted(
        [(sample.admitted_at_sec, 1) for sample in samples] + [(sample.released_at_sec, -1) for sample in samples],
        key=lambda boundary: (boundary[0], boundary[1]),
    )
    current = peak = 0
    for _, change in boundaries:
        current += change
        peak = max(peak, current)
    return peak


async def collect_admission_samples(booking_api: BookingApi, virtual_user_count: int, hold_sec: float) -> list[AdmissionSample]:
    return list(await asyncio.gather(*(
        booking_api.hold_admitted_session(LOAD_SHOW_ID, hold_sec) for _ in range(virtual_user_count)
    )))


def build_message(report: LoadReport) -> str:
    lines = []
    admitted_count = len(report.admitted_samples)
    if not report.is_admission_limited:
        lines.append(f"{FAIL_LINE_PREFIX}T1 동시 입장 상한 미적용 · 최대 동시 입장 {report.peak_concurrent_admissions}/{report.virtual_user_count}")
    if not report.is_burst_limited:
        lines.append(f"{FAIL_LINE_PREFIX}T2 요청 속도 제한 미적용 · 연속 요청 {BURST_REQUEST_COUNT}건 차단 0건")
    if report.is_normal_rate_blocked:
        lines.append(f"{FAIL_LINE_PREFIX}T2 정상 속도 요청 차단 · {report.normal_status_codes.count(RATE_LIMITED_STATUS_CODE)}건")
    if report.server_error_count:
        listed = ", ".join(report.admission_errors[:MAX_LISTED_ERROR_COUNT])
        lines.append(f"{FAIL_LINE_PREFIX}서버 오류 · 연결 실패 {report.server_error_count}건{' · ' + listed if listed else ''}")
    lines.append(f"최대 동시 입장 {report.peak_concurrent_admissions} · 입장 {admitted_count}/{report.virtual_user_count}")
    lines.append(f"연속 요청 {BURST_REQUEST_COUNT}건 중 차단 {report.burst_status_codes.count(RATE_LIMITED_STATUS_CODE)}건"
                 f" · 정상 속도 {NORMAL_REQUEST_COUNT}건 중 차단 {report.normal_status_codes.count(RATE_LIMITED_STATUS_CODE)}건")
    if report.admitted_samples:
        lines.append(f"대기열 대기 p95 {calculate_p95([sample.wait_ms for sample in report.admitted_samples]):.0f}ms")
    if not report.is_admission_limited and report.admitted_samples:
        lines.append(f"{REFERENCE_LINE_PREFIX}VU 수 ≤ 시스템 상한이면 T1 측정 불가 · VU 수 상향")
    return MESSAGE_LINE_SEPARATOR.join(lines)


class LoadCapacitySuite:
    suite_name = "load_capacity"
    title = "부하 테스트"
    related_codes: tuple[str, ...] = ("E08", "T1", "T2")

    def __init__(self, admission_hold_sec: float = ADMISSION_HOLD_SEC) -> None:
        self.admission_hold_sec = admission_hold_sec

    def run(self, context: SuiteContext) -> SuiteResult:
        booking_api = context.system_target.booking_api
        virtual_user_count = max(context.run_config.virtual_user_count, MIN_VIRTUAL_USER_COUNT)
        capacity = booking_api.virtual_user_capacity()
        if capacity is not None and virtual_user_count > capacity:
            error = AccountPoolExhaustedError(
                f"시험 계정 부족 · VU {virtual_user_count}명 · 계정 {capacity}개 · 저장소 .env QA_TEST_ACCOUNT_COUNT 확인")
            return SuiteResult(self.suite_name, SuiteOutcome.FAILED, message=f"FAIL: {error}")

        context.report_progress(reset_before_traffic(booking_api))
        report = LoadReport(virtual_user_count)
        context.report_progress(f"T1 · VU {virtual_user_count}명 오픈 동시 진입")
        report.samples = asyncio.run(collect_admission_samples(booking_api, virtual_user_count, self.admission_hold_sec))
        context.report_progress(f"T2 · 연속 요청 {BURST_REQUEST_COUNT}건 · 정상 속도 {NORMAL_REQUEST_COUNT}건")
        report.burst_status_codes = asyncio.run(booking_api.send_request_burst(BURST_REQUEST_COUNT, 0.0))
        report.normal_status_codes = asyncio.run(booking_api.send_request_burst(NORMAL_REQUEST_COUNT, NORMAL_REQUEST_INTERVAL_SEC))

        is_passed = (report.is_admission_limited and report.is_burst_limited
                     and not report.is_normal_rate_blocked and report.server_error_count == 0)
        wait_values = [sample.wait_ms for sample in report.admitted_samples]
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED if is_passed else SuiteOutcome.FAILED,
            metrics={
                "load_peak_concurrent_admissions": float(report.peak_concurrent_admissions),
                "load_rate_limited_count": float(report.burst_status_codes.count(RATE_LIMITED_STATUS_CODE)),
                "load_server_error_count": float(report.server_error_count),
                **({"load_queue_wait_p95_ms": calculate_p95(wait_values)} if wait_values else {}),
            },
            message=build_message(report),
            details={
                "virtual_user_count": virtual_user_count,
                "admitted_count": len(report.admitted_samples),
                "admission_errors": report.admission_errors[:MAX_LISTED_ERROR_COUNT],
                "burst_status_codes": report.burst_status_codes,
                "normal_status_codes": report.normal_status_codes,
            },
        )
