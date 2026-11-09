"""부하 · T1 동시 입장 상한 · T2 요청 속도 제한 · 결함 Mock = FAIL 검출 · Live 요청 형식"""
import asyncio
import json
from pathlib import Path

import httpx

from ticket_guard_qa.domain.enums import SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, RunConfig
from ticket_guard_qa.system_targets.fake_system import FAKE_QUEUE_ADMISSION_LIMIT, build_fake_system_target
from ticket_guard_qa.system_targets.live_django_system import LiveDjangoBookingApi, VirtualUserAccountPool
from ticket_guard_qa.system_targets.target_interfaces import AdmissionSample
from ticket_guard_qa.test_suites.load_capacity import LoadCapacitySuite, calculate_peak_concurrency
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

FAST_HOLD_SEC = 0.01
VIRTUAL_USER_COUNT = 60


def build_context(system_target, virtual_user_count: int = VIRTUAL_USER_COUNT) -> SuiteContext:
    return SuiteContext(
        run_id="run-test", run_config=RunConfig(TargetKind.FAKE, ("load_capacity",), virtual_user_count=virtual_user_count),
        system_target=system_target, answer_key_repository=None, case_data_dir=Path("."),
        report_progress=lambda text, **fields: None,
    )


def failure_lines(message: str) -> list[str]:
    return [line for line in message.split(MESSAGE_LINE_SEPARATOR) if line.startswith(FAIL_LINE_PREFIX)]


def test_peak_concurrency_counts_overlap_and_release_first():
    samples = [AdmissionSample(0.0, 2.0, 0.0), AdmissionSample(1.0, 3.0, 0.0), AdmissionSample(2.0, 4.0, 0.0)]
    assert calculate_peak_concurrency(samples) == 2


def test_limited_queue_and_rate_limit_pass():
    result = LoadCapacitySuite(FAST_HOLD_SEC).run(build_context(build_fake_system_target()))
    assert result.outcome is SuiteOutcome.PASSED, result.message
    assert result.metrics["load_peak_concurrent_admissions"] == FAKE_QUEUE_ADMISSION_LIMIT
    assert result.metrics["load_rate_limited_count"] == 20.0  # 30건 중 한도 10건 초과분
    assert result.metrics["load_server_error_count"] == 0.0


def test_broken_queue_limit_fails_t1():
    system_target = build_fake_system_target()
    system_target.booking_api.state.is_queue_limit_broken = True
    result = LoadCapacitySuite(FAST_HOLD_SEC).run(build_context(system_target))
    assert result.outcome is SuiteOutcome.FAILED
    assert failure_lines(result.message) == [f"FAIL: T1 동시 입장 상한 초과 · 최대 동시 입장 {VIRTUAL_USER_COUNT} · 상한 {FAKE_QUEUE_ADMISSION_LIMIT}"]


def test_missing_rate_limit_fails_t2():
    system_target = build_fake_system_target()
    system_target.booking_api.state.is_rate_limit_missing = True
    result = LoadCapacitySuite(FAST_HOLD_SEC).run(build_context(system_target))
    assert result.outcome is SuiteOutcome.FAILED
    assert failure_lines(result.message) == ["FAIL: T2 요청 속도 제한 미적용 · 연속 요청 30건 차단 0건"]


class UnlimitedDjango:
    """대기열 즉시 통과 · 공연 목록 항상 200 · 상한 · 속도 제한 없는 시스템"""

    def __init__(self) -> None:
        self.page_request_count = 0
        self.cancel_count = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/":
            return httpx.Response(200, headers={"set-cookie": "csrftoken=token-1; Path=/"})
        if request.url.path == "/":
            self.page_request_count += 1
            return httpx.Response(200, text="<html></html>")
        body = json.loads(request.content)
        if body["action"] == "start":
            return httpx.Response(200, json={"id": "attempt-1", "stage": "queue"})
        if body["action"] == "heartbeat":
            return httpx.Response(200, json={"stage": "captcha"})
        if body["action"] == "cancel":
            self.cancel_count += 1
        return httpx.Response(200, json={})


def test_live_probes_record_admission_and_page_requests():
    django = UnlimitedDjango()
    booking_api = LiveDjangoBookingApi("http://web:8000", "ticketguard", "unused",
                                       VirtualUserAccountPool(2, "qa-password", "QA123"),
                                       transport=httpx.MockTransport(django.handle))
    sample = asyncio.run(booking_api.hold_admitted_session("blue-hour", 0.0))
    status_codes = asyncio.run(booking_api.send_request_burst(3, 0.0))
    assert sample.admitted_at_sec is not None and sample.error is None
    assert status_codes == [200, 200, 200]
    assert django.page_request_count == 3
    assert django.cancel_count == 1  # 입장 후 예매 취소로 이탈
    assert booking_api.virtual_user_capacity() == 2  # 계정 반환


def test_unknown_limit_is_reference_not_pass_or_fail(monkeypatch):
    system_target = build_fake_system_target()
    monkeypatch.setattr(system_target.booking_api, "admission_limit", lambda: None)
    result = LoadCapacitySuite(FAST_HOLD_SEC).run(build_context(system_target))
    assert result.outcome is SuiteOutcome.PASSED  # T2 · 서버 오류만 판정
    assert "참고: T1 측정 불가 · 시스템 동시 입장 상한 값 미설정" in result.message


def test_users_within_limit_cannot_measure_t1():
    result = LoadCapacitySuite(FAST_HOLD_SEC).run(build_context(build_fake_system_target(), virtual_user_count=10))
    assert f"참고: T1 측정 불가 · VU 10 ≤ 상한 {FAKE_QUEUE_ADMISSION_LIMIT}" in result.message
