"""B3 유형별 퍼널 · Live 단계별 도달 · Mock 진입 · 확정만 · 끝난 Run 화면은 저장된 퍼널"""
from datetime import datetime, timezone

import pytest

from ticket_guard_qa.domain.enums import ActorType, BookingOutcome, RunStatus, SessionStep, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import PlannedUser, RunConfig, RunSummary, SessionKey, SuiteResult, VirtualUserSessionResult
from ticket_guard_qa.traffic_generators.session_funnel import (
    ACTOR_PROGRESS_DETAIL_KEY,
    PLANNED_PROGRESS_KEY,
    build_funnel_progress,
)

BOOKED_STEPS = {"login": 60.0, "start": 40.0, "queue": 12000.0, "captcha": 50.0, "seat_select": 900.0, "confirm": 30.0}


def planned(label: str, actor_type: ActorType) -> PlannedUser:
    return PlannedUser(label, actor_type)


def session(steps: dict[str, float], outcome: BookingOutcome | None, is_error: bool = False) -> VirtualUserSessionResult:
    return VirtualUserSessionResult(SessionKey("attempt"), 1.0, is_error, step_latency_ms=steps, booking_outcome=outcome)


def test_live_sessions_fill_every_traffic_step():
    users = [planned("u1", ActorType.BOT_C), planned("u2", ActorType.BOT_C), planned("u3", ActorType.BOT_C)]
    results = [
        session(BOOKED_STEPS, BookingOutcome.BOOKED),
        session({**BOOKED_STEPS, "seat_select": 0.0, "confirm": 0.0}, BookingOutcome.SOLD_OUT),  # 원하는 좌석 전부 팔림
        None,  # 아직 진행 중
    ]
    progress = build_funnel_progress(users, results)[ActorType.BOT_C.value]

    assert progress == {
        PLANNED_PROGRESS_KEY: 3, SessionStep.ENTERED.value: 2, SessionStep.QUEUE_PASSED.value: 2,
        SessionStep.CAPTCHA_PASSED.value: 2, SessionStep.SEAT_SELECTED.value: 1, SessionStep.CONFIRMED.value: 1,
    }


def test_session_stopped_at_login_is_not_entered():
    progress = build_funnel_progress([planned("u1", ActorType.HUMAN)], [session({"login": 60.0}, BookingOutcome.SOLD_OUT)])
    assert progress[ActorType.HUMAN.value][SessionStep.ENTERED.value] == 0


def test_mock_sessions_fill_only_entered_and_confirmed():
    users = [planned("u1", ActorType.HUMAN), planned("u2", ActorType.HUMAN)]
    progress = build_funnel_progress(users, [session({}, BookingOutcome.BOOKED), session({}, BookingOutcome.SOLD_OUT)])
    assert progress[ActorType.HUMAN.value] == {PLANNED_PROGRESS_KEY: 2, SessionStep.ENTERED.value: 2, SessionStep.CONFIRMED.value: 1}


pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ticket_guard_qa.dashboard.dashboard_app import create_dashboard_app  # noqa: E402
from ticket_guard_qa.dashboard.dependencies import ADMIN_USER_HEADER  # noqa: E402


def test_finished_live_run_shows_saved_funnel_on_b3(qa_settings):
    client = TestClient(create_dashboard_app(qa_settings), headers={ADMIN_USER_HEADER: "qa-admin"})
    repository = client.app.state.run_service.run_repository
    run_config = RunConfig(TargetKind.LIVE, ("booking_flow",), virtual_user_count=20)
    started_at = datetime(2026, 11, 10, tzinfo=timezone.utc)
    repository.create_run("run-funnel", run_config, started_at)
    saved_progress = {ActorType.HUMAN.value: {
        PLANNED_PROGRESS_KEY: 16, SessionStep.ENTERED.value: 16, SessionStep.QUEUE_PASSED.value: 15,
        SessionStep.CAPTCHA_PASSED.value: 14, SessionStep.SEAT_SELECTED.value: 13, SessionStep.CONFIRMED.value: 7,
    }}
    repository.save_summary(RunSummary("run-funnel", run_config, RunStatus.PASSED, started_at, started_at, [
        SuiteResult("booking_flow", SuiteOutcome.PASSED, details={ACTOR_PROGRESS_DETAIL_KEY: saved_progress}),
    ]))

    page = client.get("/runs/run-funnel/bots/live").text
    assert "<th>대기열</th><th>보안문자</th>" in page
    assert 'data-step="CAPTCHA_PASSED">\n            <span class="step-count">14</span>' in page
    assert "봇 트래픽 미발생" not in page  # 예매 흐름 = 트래픽 Suite
