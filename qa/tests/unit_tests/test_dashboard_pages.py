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


@pytest.mark.parametrize("path", ["/", "/runs/new", "/db", "/db/sessions/attempt-1", "/bots", "/bots/bot_a/edit"])
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


def test_unknown_run_is_404(dashboard_client):
    assert dashboard_client.get("/runs/run-missing").status_code == 404


def test_wrong_traffic_mix_is_rejected(dashboard_client):
    response = dashboard_client.post("/runs", data={
        "suite_names": ["self_check"], "target_kind": "fake", "human_percent": "90", "bot_a_percent": "50",
    })
    assert response.status_code == 400
    assert "100" in response.text


def test_full_fake_run_shows_result(dashboard_client):
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
