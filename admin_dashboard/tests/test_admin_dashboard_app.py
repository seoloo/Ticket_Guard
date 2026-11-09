"""관리자 독립 앱 · QA DB 초기화 금지와 게이트웨이 인증"""
from fastapi.testclient import TestClient
import subprocess
import sys

from ticket_guard_admin.app import AdminSettings, create_admin_dashboard_app
from ticket_guard_admin.mongo_reader import build_dashboard


def test_standalone_admin_does_not_initialize_qa_database():
    # 새 프로세스에서 QA 패키지의 모든 import를 차단하고 관리자 앱 생성.
    code = '''
import importlib.abc
import sys
class RejectQa(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ticket_guard_qa" or fullname.startswith("ticket_guard_qa."):
            raise AssertionError("QA dependency: " + fullname)
sys.meta_path.insert(0, RejectQa())
from ticket_guard_admin.app import create_admin_dashboard_app
from ticket_guard_admin.settings import AdminSettings
create_admin_dashboard_app(AdminSettings(mongo_uri="", _env_file=None))
'''
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    app = create_admin_dashboard_app(AdminSettings(mongo_uri="", _env_file=None))
    client = TestClient(app)
    assert client.get("/").status_code == 403
    response = client.get("/", headers={"X-Admin-User": "manager"})
    assert response.status_code == 200
    assert "DB 조회 실패" in response.text
    assert "샘플 데이터" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_live_page_renders_actual_database_and_empty_data(monkeypatch):
    result = build_dashboard([]) | {"database": "ticketguard", "counts": {"clean_events": 0, "quarantine_events": 0, "event_metrics": 0},
                                    "matched": 0, "is_truncated": False, "limit": 5000, "reasons": [], "options": [], "loaded_at": "now"}
    monkeypatch.setattr("ticket_guard_admin.pages.AdminMongoReader.read_dashboard", lambda *args, **kwargs: result)
    app = create_admin_dashboard_app(AdminSettings(mongo_uri="mongodb://unused/ticketguard", _env_file=None))
    response = TestClient(app).get("/", headers={"X-Admin-User": "manager"})
    assert response.status_code == 200
    assert "ticketguard.clean_events" in response.text
    assert "집계 불가" in response.text
    assert 'href="/admin/admin-static/dashboard.css"' in response.text
    assert "USR-2004" not in response.text
