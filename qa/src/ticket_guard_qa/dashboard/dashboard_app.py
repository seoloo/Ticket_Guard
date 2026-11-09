"""대시보드 앱 조립 · 팀 입구 127.0.0.1:8000/qa/ 뒤에서만 · AGENTS.md 4장"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.dashboard.dependencies import TargetStatusChecker, require_admin
from ticket_guard_qa.dashboard.routes import db_dashboard_routes, home_routes, macro_bot_routes, test_run_routes
from ticket_guard_qa.dashboard.screen_format import register_screen_filters
from ticket_guard_qa.macro_bots.bot_catalog import BOT_TYPE_CATALOG
from ticket_guard_qa.qa_database.database import create_qa_database_engine, create_session_factory
from ticket_guard_qa.settings import Settings, load_settings
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService

DASHBOARD_DIR = Path(__file__).resolve().parent


def create_dashboard_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    session_factory = create_session_factory(create_qa_database_engine(settings.qa_database_url))
    progress_stream = RunProgressStream()
    base_path = settings.dashboard_base_path.rstrip("/")

    app = FastAPI(title="티켓가드 QA 대시보드")
    app.state.settings = settings
    app.state.base_path = base_path
    app.state.progress_stream = progress_stream
    app.state.run_service = RunService(settings, session_factory, progress_stream)
    app.state.run_service.run_repository.mark_unfinished_runs_as_error(datetime.now(timezone.utc))
    app.state.answer_key_repository = AnswerKeyRepository(session_factory)
    app.state.qa_session_factory = session_factory
    app.state.target_status_checker = TargetStatusChecker(settings)

    templates = Jinja2Templates(directory=DASHBOARD_DIR / "templates")
    templates.env.globals["base_path"] = base_path  # 링크 앞에 /qa
    templates.env.globals["bot_type_catalog"] = BOT_TYPE_CATALOG  # 봇 이름 · 색 · 화면 어디서나
    templates.env.globals["static_version"] = int(datetime.now(timezone.utc).timestamp())  # 다시 띄우면 CSS 새로 받음
    register_screen_filters(templates.env)
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR / "static"), name="static")
    for routes in (home_routes, test_run_routes, db_dashboard_routes, macro_bot_routes):
        app.include_router(routes.router, dependencies=[Depends(require_admin)])
    return app
