"""관리자 05 화면 · DB 미연결과 게이트웨이 인증 경계 회귀 검사"""
import pytest
from fastapi.testclient import TestClient

from ticket_guard_admin.preview_data import build_preview_data
from ticket_guard_admin.app import create_admin_dashboard_app
from ticket_guard_admin.dependencies import ADMIN_USER_HEADER


def test_preview_never_connects_to_system_database(admin_settings, monkeypatch):
    def reject_connection(*args, **kwargs):
        pytest.fail("관리자 예시 화면에서 MongoDB 연결 시도")

    admin_settings.mongo_uri = "mongodb://unused.invalid:27017/ticketguard"
    app = create_admin_dashboard_app(admin_settings)
    monkeypatch.setattr("pymongo.MongoClient", reject_connection)
    monkeypatch.setattr("ticket_guard_admin.mongo_reader.MongoClient", reject_connection)
    client = TestClient(app, headers={ADMIN_USER_HEADER: "admin-preview"})
    page = client.get("/preview?run_id=%3Cscript%3E")
    assert page.status_code == 200
    assert "샘플 데이터 기반 화면 시안 · 실제 DB 연결 없음" in page.text
    assert all(title in page.text for title in ("흐름 분석", "의심 활동", "사용자 상세"))
    assert "RUNNING" not in page.text
    assert "&lt;script&gt;" in page.text
    assert 'href="/qa/"' in page.text
    assert 'href="/qa/runs/new"' in page.text
    assert 'href="/admin/admin-static/dashboard.css"' in page.text
    assert client.get("/admin-static/dashboard.css").status_code == 200
    assert client.get("/admin-static/dashboard.js").status_code == 200


def test_preview_requires_gateway_admin(admin_settings):
    client = TestClient(create_admin_dashboard_app(admin_settings))
    assert client.get("/preview").status_code == 403
    assert client.get("/preview", headers={ADMIN_USER_HEADER: "  "}).status_code == 403


def test_preview_review_storage_is_scoped_to_authenticated_admin(admin_settings):
    client = TestClient(create_admin_dashboard_app(admin_settings))
    for username in ("admin-one", "admin-two"):
        page = client.get("/preview", headers={ADMIN_USER_HEADER: username})
        assert page.status_code == 200
        assert f'data-review-owner="{username}"' in page.text
        assert 'data-review-scope="/admin"' in page.text


def test_preview_funnel_and_review_counts_are_consistent():
    preview = build_preview_data()
    assert [count for _, count in preview["funnel"]] == [1000, 900, 810, 740, 620]
    assert len(preview["users"]) == 12
    assert len({user["id"] for user in preview["users"]}) == 12
    assert {priority: sum(user["priority"] == priority for user in preview["users"])
            for priority in ("우선 검토", "관찰", "데이터 확인")} == {"우선 검토": 3, "관찰": 7, "데이터 확인": 2}
