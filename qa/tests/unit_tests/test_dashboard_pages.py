import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ticket_guard_qa.dashboard.dashboard_app import create_dashboard_app  # noqa: E402
from ticket_guard_qa.dashboard.dependencies import ADMIN_USER_HEADER  # noqa: E402

ADMIN_HEADERS = {ADMIN_USER_HEADER: "qa-admin"}  # 팀 입구(nginx)가 붙이는 헤더 흉내


@pytest.fixture
def dashboard_client(qa_settings) -> TestClient:
    return TestClient(create_dashboard_app(qa_settings), headers=ADMIN_HEADERS)


@pytest.mark.parametrize("path", ["/", "/runs/new", "/db", "/db/sessions/attempt-1", "/bots", "/bots/bot_a/edit", "/bots/bot_new/edit"])
def test_screens_open_for_admin(dashboard_client, path):
    assert dashboard_client.get(path).status_code == 200


def test_missing_admin_header_is_forbidden(qa_settings):
    client = TestClient(create_dashboard_app(qa_settings))
    assert client.get("/").status_code == 403


def test_blank_admin_header_is_forbidden(qa_settings):
    client = TestClient(create_dashboard_app(qa_settings), headers={ADMIN_USER_HEADER: "  "})
    assert client.get("/").status_code == 403


def test_links_use_gateway_base_path(dashboard_client):
    page = dashboard_client.get("/").text
    assert 'href="/qa/runs/new"' in page
    assert "/qa/static/css/theme_tokens.css?v=" in page


@pytest.mark.parametrize("path", ["/runs/run-missing", "/runs/run-missing/bots", "/runs/run-missing/bots/live", "/bots/bot_z/edit"])
def test_unknown_run_or_bot_is_404(dashboard_client, path):
    assert dashboard_client.get(path).status_code == 404


def test_bot_screens_need_admin(qa_settings):
    client = TestClient(create_dashboard_app(qa_settings))
    assert client.get("/bots").status_code == 403
    assert client.post("/bots/bot_a/versions", data={}).status_code == 403


BOT_B_FORM = {
    "entry_delay_after_open_ms": "200", "entry_delay_deviation_ms": "150",
    "click_interval_mean_ms": "400", "click_interval_deviation_ms": "200", "sessions_per_device": "1",
}


def test_bot_trial_shows_score_without_saving(dashboard_client):
    response = dashboard_client.post("/bots/bot_b/trial", data=BOT_B_FORM)
    assert response.status_code == 200
    assert "탐지" in response.text and "저장 안 한 변경" in response.text
    assert "v2" not in dashboard_client.get("/bots").text


def test_wrong_bot_input_is_rejected(dashboard_client):
    response = dashboard_client.post("/bots/bot_b/versions", data=BOT_B_FORM | {"sessions_per_device": "0"})
    assert response.status_code == 400
    assert "기기당 세션 수" in response.text


def test_locked_bot_save_is_rejected(dashboard_client):
    response = dashboard_client.post("/bots/bot_new/versions", data=BOT_B_FORM)
    assert response.status_code == 400
    assert "평가 전용" in response.text


def test_wrong_traffic_mix_is_rejected(dashboard_client):
    response = dashboard_client.post("/runs", data={
        "suite_names": ["self_check"], "target_kind": "fake", "human_percent": "90", "bot_a_percent": "50",
    })
    assert response.status_code == 400
    assert "100" in response.text


def test_full_fake_run_shows_result(dashboard_client):
    saved = dashboard_client.post("/bots/bot_b/versions", data=BOT_B_FORM | {"change_note": "흔들림 키움"}, follow_redirects=False)
    assert saved.headers["location"] == "/qa/bots/bot_b/edit?saved_version=2"
    response = dashboard_client.post("/runs", data={
        "suite_names": ["self_check", "verdict_accuracy", "pipeline_latency"], "target_kind": "fake",
        "virtual_user_count": "100", "duration_sec": "300", "alert_policy": "on_failure", "is_open_burst": "on",
        "human_percent": "80", "bot_a_percent": "5", "bot_b_percent": "5", "bot_c_percent": "5", "bot_d_percent": "5",
    }, follow_redirects=False)
    assert response.status_code == 303
    live_path = response.headers["location"].removeprefix("/qa")
    run_path = live_path.removesuffix("/live")

    run_service = dashboard_client.app.state.run_service
    for _ in range(100):  # 배경 실행 끝날 때까지 · 가짜 실행 시간 0초
        if run_service.active_run_id is None:
            break
        time.sleep(0.05)

    result_page = dashboard_client.get(run_path)
    assert result_page.status_code == 200
    assert "정답표를 저장했어요" in result_page.text
    assert dashboard_client.get(f"{run_path}/report.json").status_code == 200
    assert dashboard_client.get(live_path, follow_redirects=False).status_code == 303  # 끝난 실행 → 04

    run_id = run_path.rsplit("/", 1)[-1]
    assert run_service.run_repository.get_summary(run_id).run_config.bot_version_numbers["BOT_B"] == 2  # 저장한 버전으로 실행
    detection_page = dashboard_client.get(f"{run_path}/bots")
    assert detection_page.status_code == 200 and "정답 × 판정" in detection_page.text
    live_bot_page = dashboard_client.get(f"{run_path}/bots/live")
    assert live_bot_page.status_code == 200 and "실행이 끝났어요" in live_bot_page.text
    assert run_id in dashboard_client.get("/bots").text  # B1 카드가 최근 실행을 씀
