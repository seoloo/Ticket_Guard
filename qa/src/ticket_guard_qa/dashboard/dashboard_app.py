"""대시보드 앱 조립 · ticket-guard-qa dashboard로만 실행 · 포트 8800 · AGENTS.md 4장"""
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.dashboard.dependencies import require_admin
from ticket_guard_qa.dashboard.routes import db_dashboard_routes, home_routes, macro_bot_routes, test_run_routes
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry
from ticket_guard_qa.qa_database.database import create_qa_database_engine, create_session_factory
from ticket_guard_qa.settings import Settings, load_settings
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService

DASHBOARD_DIR = Path(__file__).resolve().parent


def create_dashboard_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    session_factory = create_session_factory(create_qa_database_engine(settings.qa_database_url))
    progress_stream = RunProgressStream()

    app = FastAPI(title="티켓가드 QA 대시보드")
    app.state.settings = settings
    app.state.progress_stream = progress_stream
    app.state.run_service = RunService(settings, session_factory, progress_stream)
    app.state.answer_key_repository = AnswerKeyRepository(session_factory)
    app.state.bot_profile_registry = BotProfileRegistry()
    app.state.templates = Jinja2Templates(directory=DASHBOARD_DIR / "templates")

    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR / "static"), name="static")
    for routes in (home_routes, test_run_routes, db_dashboard_routes, macro_bot_routes):
        app.include_router(routes.router, dependencies=[Depends(require_admin)])
    return app
