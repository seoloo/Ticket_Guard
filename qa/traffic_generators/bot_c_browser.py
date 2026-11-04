"""봇 C · 브라우저 자동화(Playwright) · 우리 앱 주소에만 접속 · browser 묶음 설치 필요"""
from ticket_guard_qa.settings import load_settings


def run_bot_c_session(virtual_user_label: str) -> str:
    """가상 사용자 라벨 → 시스템이 준 세션 키"""
    settings = load_settings()
    # TODO(트래픽 생성기 구현 시): settings.system_base_url만 열기 · 화면 캡처 저장 → B3
    raise NotImplementedError(f"봇 C 미구현 · 대상 {settings.system_base_url}")
