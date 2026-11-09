import re
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


@pytest.mark.parametrize("path", ["/", "/runs/new", "/db", "/db/sessions/attempt-1", "/bots", "/bots/bot_a/edit", "/bots/bot_new/edit", "/cases"])
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
    assert "Hit" in response.text and "미저장 변경 사항" in response.text
    assert "v2" not in dashboard_client.get("/bots").text


def test_wrong_bot_input_is_rejected(dashboard_client):
    response = dashboard_client.post("/bots/bot_b/versions", data=BOT_B_FORM | {"sessions_per_device": "0"})
    assert response.status_code == 400
    assert "범위 오류" in response.text


def test_locked_bot_save_is_rejected(dashboard_client):
    response = dashboard_client.post("/bots/bot_new/versions", data=BOT_B_FORM)
    assert response.status_code == 400
    assert "읽기 전용 프로필" in response.text


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
    assert "Ground Truth 저장 완료" in result_page.text
    assert dashboard_client.get(f"{run_path}/report.json").status_code == 200
    assert dashboard_client.get(live_path, follow_redirects=False).status_code == 303  # 끝난 실행 → 04

    run_id = run_path.rsplit("/", 1)[-1]
    assert run_service.run_repository.get_summary(run_id).run_config.bot_version_numbers["BOT_B"] == 2  # 저장한 버전으로 실행

    cases_page = dashboard_client.get(f"/cases?run_id={run_id}").text
    assert f"Run <b class=\"mono\">{run_id}</b> · 세션 100" in cases_page  # 정답표 조회
    detection_page = dashboard_client.get(f"{run_path}/bots")
    assert detection_page.status_code == 200 and "Confusion Matrix" in detection_page.text
    assert "MOCK-R" in detection_page.text  # SESSION_VERDICTS.matchedRules → 룰별 Hit 수
    live_bot_page = dashboard_client.get(f"{run_path}/bots/live")
    assert "Mock 캡처" in live_bot_page.text and "예매 확정" in live_bot_page.text  # 봇 C 5% · Mock 프레임
    assert live_bot_page.status_code == 200 and "Run 종료" in live_bot_page.text
    assert run_id in dashboard_client.get("/bots").text  # B1 카드가 최근 실행을 씀


def test_raw_ingest_suite_button_and_result(dashboard_client):
    assert 'value="raw_ingest"' in dashboard_client.get("/runs/new").text  # Run 설정 Suite 버튼
    response = dashboard_client.post("/runs", data={
        "suite_names": ["raw_ingest"], "target_kind": "fake", "virtual_user_count": "20", "duration_sec": "120",
        "alert_policy": "never", "human_percent": "80", "bot_a_percent": "5", "bot_b_percent": "5",
        "bot_c_percent": "5", "bot_d_percent": "5",
    }, follow_redirects=False)
    run_path = response.headers["location"].removeprefix("/qa").removesuffix("/live")
    run_service = dashboard_client.app.state.run_service
    for _ in range(100):
        if run_service.active_run_id is None:
            break
        time.sleep(0.05)
    result_page = dashboard_client.get(run_path).text
    assert "원본 적재 검증" in result_page and "원본 적재 160/160" in result_page


def test_booking_flow_suite_button_and_result(dashboard_client):
    assert 'value="booking_flow"' in dashboard_client.get("/runs/new").text  # Run 설정 Suite 버튼
    response = dashboard_client.post("/runs", data={
        "suite_names": ["booking_flow"], "target_kind": "fake", "virtual_user_count": "20", "duration_sec": "120",
        "alert_policy": "never", "human_percent": "80", "bot_a_percent": "5", "bot_b_percent": "5",
        "bot_c_percent": "5", "bot_d_percent": "5",
    }, follow_redirects=False)
    run_path = response.headers["location"].removeprefix("/qa").removesuffix("/live")
    run_service = dashboard_client.app.state.run_service
    for _ in range(100):
        if run_service.active_run_id is None:
            break
        time.sleep(0.05)
    result_page = dashboard_client.get(run_path).text
    assert "예매 흐름 테스트" in result_page and "예매 완료 20 · 매진 0 · 오류 0 / VU 20" in result_page


def test_capture_image_route_rejects_other_files(dashboard_client):
    assert dashboard_client.get("/runs/run-1/captures/..%2Fsecret.png").status_code == 404
    assert dashboard_client.get("/runs/run-1/captures/frame.txt").status_code == 404


def test_run_setup_starts_without_suites_and_shows_guides(dashboard_client):
    page = dashboard_client.get("/runs/new").text
    suite_inputs = re.findall(r'<input[^>]*name="suite_names"[^>]*>', page)
    assert len(suite_inputs) == 10 and not any("checked" in tag for tag in suite_inputs)
    assert page.count('role="tooltip"') == 10
    assert "같은 좌석 동시 결제 시 중복 판매 여부" in page
    assert page.count("<b>검증 대상</b>") == 10 and page.count("<b>검증 방법</b>") == 10
