"""관리자 테스트 설정 · 실제 DB 연결과 QA 패키지 사용 없음"""
import pytest

from ticket_guard_admin.settings import AdminSettings


@pytest.fixture
def admin_settings():
    return AdminSettings(mongo_uri="", base_path="/admin", _env_file=None)
