"""Live 예상 소요 시간 · 계산 · 최근 실측 보정 · 최대 시간(자동 · 설정) · Suite 실제 소요 기록 · 02 예상 API"""
from dataclasses import replace

import pytest

from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.domain.models import RunConfig, TrafficMix
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry
from ticket_guard_qa.test_runs import run_estimate
from ticket_guard_qa.test_runs.run_estimate import (
    ESTIMATE_FROM_FORMULA,
    ESTIMATE_FROM_HISTORY,
    MAX_AUTO_TIME_LIMIT_SEC,
    MIN_AUTO_TIME_LIMIT_SEC,
    estimate_live_run,
)
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService

LIVE_SUITES = ("self_check", "booking_flow", "event_delivery")
HUMAN_ONLY_MIX = TrafficMix({"HUMAN": 100})
BROWSER_HEAVY_MIX = TrafficMix({"HUMAN": 50, "BOT_C": 50})


def build_live_config(**overrides) -> RunConfig:
    return replace(RunConfig(TargetKind.LIVE, LIVE_SUITES, virtual_user_count=200, duration_sec=0), **overrides)


def test_formula_estimate_adds_suites_and_sets_auto_limit():
    estimate = estimate_live_run(build_live_config(), BotProfileRegistry(), 0, [])

    seconds_by_suite = {suite.suite_name: suite.seconds for suite in estimate.suites}
    assert [suite.suite_name for suite in estimate.suites] == list(LIVE_SUITES)  # 실행 순서 그대로
    assert {suite.source for suite in estimate.suites} == {ESTIMATE_FROM_FORMULA}
    assert seconds_by_suite["booking_flow"] == seconds_by_suite["event_delivery"]  # 같은 VU 트래픽
    assert estimate.total_sec == pytest.approx(sum(seconds_by_suite.values()))
    assert estimate.is_time_limit_auto and MIN_AUTO_TIME_LIMIT_SEC <= estimate.traffic_time_limit_sec <= MAX_AUTO_TIME_LIMIT_SEC
    assert estimate.low_sec < estimate.total_sec < estimate.high_sec


def test_browser_bots_waiting_for_browser_slots_take_longer():
    registry = BotProfileRegistry()
    human_only = run_estimate.calculate_traffic_suite_sec(build_live_config(traffic_mix=HUMAN_ONLY_MIX), registry, 25)
    browser_heavy = run_estimate.calculate_traffic_suite_sec(build_live_config(traffic_mix=BROWSER_HEAVY_MIX), registry, 25)
    assert browser_heavy > human_only  # 브라우저 VU 100명 · 동시 4개씩 차례


def test_recent_live_durations_replace_formula_and_scale_by_virtual_users():
    samples = [("booking_flow", 100, 60.0), ("booking_flow", 100, 80.0), ("self_check", 50, 3.0)]
    estimate = estimate_live_run(build_live_config(), BotProfileRegistry(), 0, samples)

    by_suite = {suite.suite_name: suite for suite in estimate.suites}
    assert (by_suite["booking_flow"].seconds, by_suite["booking_flow"].source) == (140.0, ESTIMATE_FROM_HISTORY)  # 중앙값 70초 × 200/100
    assert by_suite["self_check"].seconds == 3.0  # 트래픽 없는 Suite = VU 환산 없음
    assert by_suite["event_delivery"].source == ESTIMATE_FROM_FORMULA  # 실측 없음


def test_set_time_limit_caps_traffic_suite_estimate():
    samples = [("booking_flow", 200, 900.0)]
    estimate = estimate_live_run(build_live_config(duration_sec=120), BotProfileRegistry(), 0, samples)

    booking = next(suite for suite in estimate.suites if suite.suite_name == "booking_flow")
    assert (estimate.traffic_time_limit_sec, estimate.is_time_limit_auto) == (120, False)
    assert booking.seconds <= 120 + run_estimate.PRE_OPEN_LOGIN_SEC  # 최대 시간 넘으면 남은 VU 시간 초과로 끝남


def test_suite_duration_is_recorded_for_next_estimate(qa_settings, qa_database):
    run_service = RunService(qa_settings, qa_database, RunProgressStream())
    summary = run_service.run_now(RunConfig(TargetKind.FAKE, ("self_check",)))

    assert summary.suite_results[0].duration_sec is not None
    stored = run_service.run_repository.get_summary(summary.run_id)
    assert stored.suite_results[0].duration_sec == summary.suite_results[0].duration_sec
    assert run_service.run_repository.list_recent_suite_durations(TargetKind.FAKE.value, 5)[0][:2] == ("self_check", 200)


def test_mock_run_keeps_fixed_simulation_time(qa_settings, qa_database):
    run_service = RunService(qa_settings, qa_database, RunProgressStream())
    mock_config = RunConfig(TargetKind.FAKE, LIVE_SUITES, duration_sec=0)
    assert run_service.estimate_run(mock_config) is None
    assert run_service.measurement_window_sec(mock_config) == qa_settings.fake_run_duration_sec
    assert run_service.traffic_time_limit_sec(mock_config, None) == 300  # 0(자동)이어도 Mock 트래픽은 기본 제한


def test_estimate_api_returns_suite_breakdown_for_live(qa_settings):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ticket_guard_qa.dashboard.dashboard_app import create_dashboard_app
    from ticket_guard_qa.dashboard.dependencies import ADMIN_USER_HEADER

    client = TestClient(create_dashboard_app(qa_settings), headers={ADMIN_USER_HEADER: "qa-admin"})
    form = {"target_kind": "live", "suite_names": list(LIVE_SUITES), "virtual_user_count": "200", "duration_sec": "0",
            "percent_HUMAN": "80", "percent_BOT_C": "20"}
    live = client.post("/runs/estimate", data=form).json()
    assert [suite["suite_name"] for suite in live["suites"]] == list(LIVE_SUITES)
    assert live["is_time_limit_auto"] and live["low_sec"] <= live["total_sec"] <= live["high_sec"]

    mock = client.post("/runs/estimate", data={**form, "target_kind": "fake"}).json()
    assert (mock["total_sec"], mock["suites"]) == (qa_settings.fake_run_duration_sec, [])
