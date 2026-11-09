"""장애 복구 · Mock 저장 작업 중지 · 재시작 · 결함 Mock = FAIL 검출 · Live Docker 요청 형식"""
from pathlib import Path

import httpx
import pytest

from ticket_guard_qa.domain.enums import SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, RunConfig
from ticket_guard_qa.settings import QA_ROOT_DIR
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.system_targets.live_django_system import LiveDockerProcessControl
from ticket_guard_qa.system_targets.target_interfaces import PIPELINE_SERVICE_NAME
from ticket_guard_qa.test_suites.failure_recovery import EVENT_COUNT_PER_PHASE, FailureRecoverySuite
from ticket_guard_qa.test_suites.suite_interface import SuiteContext

CASE_DATA_DIR = QA_ROOT_DIR / "case_data"


def build_context(system_target) -> SuiteContext:
    return SuiteContext(
        run_id="run-test", run_config=RunConfig(TargetKind.FAKE, ("failure_recovery",)), system_target=system_target,
        answer_key_repository=None, case_data_dir=CASE_DATA_DIR, report_progress=lambda text, **fields: None,
    )


def run_suite(system_target):
    return FailureRecoverySuite(timeout_sec=0.0, poll_interval_sec=0.0).run(build_context(system_target))


def failure_lines(message: str) -> list[str]:
    return [line for line in message.split(MESSAGE_LINE_SEPARATOR) if line.startswith(FAIL_LINE_PREFIX)]


def test_pipeline_restart_without_loss_passes():
    system_target = build_fake_system_target()
    result = run_suite(system_target)
    assert result.outcome is SuiteOutcome.PASSED, result.message
    assert result.metrics["failure_recovery_missing_count"] == 0.0
    assert result.metrics["failure_recovery_duplicate_count"] == 0.0
    assert "recovery_time_sec" in result.metrics
    assert system_target.booking_api.state.is_pipeline_running


def test_lost_backlog_is_reported_as_missing():
    system_target = build_fake_system_target()
    system_target.booking_api.state.is_backlog_lost = True
    result = run_suite(system_target)
    assert result.outcome is SuiteOutcome.FAILED
    assert failure_lines(result.message)[0].startswith(f"FAIL: 재시작 후 누락 {EVENT_COUNT_PER_PHASE}건")
    assert "recovery_time_sec" not in result.metrics


def test_broken_checkpoint_is_reported_as_duplicate():
    system_target = build_fake_system_target()
    system_target.booking_api.state.is_checkpoint_broken = True
    result = run_suite(system_target)
    assert result.outcome is SuiteOutcome.FAILED
    assert failure_lines(result.message) == [f"FAIL: 재시작 후 중복 저장 {EVENT_COUNT_PER_PHASE}건 · checkpoint 이후 재처리"]


def test_live_docker_control_posts_stop_and_start():
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.method} {request.url.path}")
        return httpx.Response(204)

    control = LiveDockerProcessControl({PIPELINE_SERVICE_NAME: "ticket-guard-spark-1"}, "/unused.sock",
                                       transport=httpx.MockTransport(handle))
    control.stop_service(PIPELINE_SERVICE_NAME)
    control.start_service(PIPELINE_SERVICE_NAME)
    assert requests == ["POST /containers/ticket-guard-spark-1/stop", "POST /containers/ticket-guard-spark-1/start"]


def test_live_docker_control_without_container_name_is_skipped():
    control = LiveDockerProcessControl({PIPELINE_SERVICE_NAME: ""}, "/unused.sock")
    with pytest.raises(NotImplementedError):
        control.stop_service(PIPELINE_SERVICE_NAME)
