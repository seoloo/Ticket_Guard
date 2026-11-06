"""화면에서 쓰는 공용 객체 · 관리자 확인(A안) · 주소 앞부분(/qa)"""
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileStore
from ticket_guard_qa.settings import Settings
from ticket_guard_qa.system_targets.target_factory import build_system_target
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService

ADMIN_USER_HEADER = "X-Admin-User"  # 팀 입구가 브라우저 값을 지우고 다시 씀
TARGET_STATUS_CACHE_SEC = 15


def require_admin(request: Request) -> None:
    """팀 입구(nginx)가 Django에 확인하고 붙인 헤더만 믿음 · A안"""
    admin_user = request.headers.get(ADMIN_USER_HEADER, "").strip()
    if not admin_user:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    request.state.admin_user = admin_user


@dataclass(frozen=True)
class TargetStatus:
    target_kind: TargetKind
    label: str
    is_connected: bool


class TargetStatusChecker:
    """헤더 연결 상태 · 화면마다 시스템에 묻지 않도록 잠깐 저장"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cached_status: TargetStatus | None = None
        self._checked_at = 0.0

    def get_status(self) -> TargetStatus:
        if self._cached_status and time.monotonic() - self._checked_at < TARGET_STATUS_CACHE_SEC:
            return self._cached_status
        if self.settings.target_kind is TargetKind.FAKE:
            status = TargetStatus(TargetKind.FAKE, "Mock", True)
        else:
            is_connected = build_system_target(self.settings).booking_api.check_health()
            status = TargetStatus(TargetKind.LIVE, "Live", is_connected)
        self._cached_status, self._checked_at = status, time.monotonic()
        return status


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_progress_stream(request: Request) -> RunProgressStream:
    return request.app.state.progress_stream


def get_answer_key_repository(request: Request) -> AnswerKeyRepository:
    return request.app.state.answer_key_repository


def get_bot_profile_store(request: Request) -> BotProfileStore:
    return request.app.state.run_service.bot_profile_store  # 실행과 같은 저장소


def build_page_url(request: Request, path: str) -> str:
    return f"{request.app.state.base_path}{path}"


def redirect_to_page(request: Request, path: str) -> RedirectResponse:
    return RedirectResponse(build_page_url(request, path), status_code=303)


def render_screen(request: Request, template_name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    screen_context = {
        "admin_user": getattr(request.state, "admin_user", ""),
        "target_status": request.app.state.target_status_checker.get_status(),
        **context,
    }
    return templates.TemplateResponse(request, template_name, screen_context, status_code=status_code)
