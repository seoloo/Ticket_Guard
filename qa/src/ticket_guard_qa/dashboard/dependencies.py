"""화면에서 쓰는 공용 객체 · 관리자 확인"""
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry
from ticket_guard_qa.settings import Settings
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService


def require_admin(request: Request) -> None:
    # TODO(EC2 배포 전 필수): 관리자 로그인 · 지금은 127.0.0.1에서만 열어서 사용
    return None


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_progress_stream(request: Request) -> RunProgressStream:
    return request.app.state.progress_stream


def get_answer_key_repository(request: Request) -> AnswerKeyRepository:
    return request.app.state.answer_key_repository


def get_bot_profile_registry(request: Request) -> BotProfileRegistry:
    return request.app.state.bot_profile_registry


def render_screen(request: Request, template_name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, template_name, context, status_code=status_code)
