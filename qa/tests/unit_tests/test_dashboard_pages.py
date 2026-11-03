import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ticket_guard_qa.dashboard.dashboard_app import create_dashboard_app  # noqa: E402


@pytest.fixture
def dashboard_client(qa_settings) -> TestClient:
    return TestClient(create_dashboard_app(qa_settings))


@pytest.mark.parametrize("path", ["/", "/runs/new", "/db", "/db/sessions/attempt-1", "/bots", "/bots/bot_a/edit"])
def test_screens_open(dashboard_client, path):
    assert dashboard_client.get(path).status_code == 200


def test_unknown_run_is_404(dashboard_client):
    assert dashboard_client.get("/runs/run-missing").status_code == 404


def test_start_run_redirects_to_live_screen(dashboard_client):
    response = dashboard_client.post("/runs", data={"suite_names": ["self_check"], "target_kind": "fake"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/live")
