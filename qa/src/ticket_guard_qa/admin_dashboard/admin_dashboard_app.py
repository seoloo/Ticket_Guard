"""QA 실행 화면과 분리된 관리자 운영 대시보드."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ticket_guard_qa.dashboard.dependencies import require_admin
from ticket_guard_qa.admin_dashboard.routes import routes
from ticket_guard_qa.settings import Settings, load_settings
from ticket_guard_qa.system_targets.live_mongo_reader import LiveMongoPipelineReader

ADMIN_DIR = Path(__file__).resolve().parent


def create_admin_dashboard_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="티켓가드 관리자 운영 대시보드")
    app.state.settings = settings
    app.state.base_path = settings.admin_dashboard_base_path.rstrip("/")
    app.state.pipeline_reader = LiveMongoPipelineReader(settings.system_mongo_uri)
    templates = Jinja2Templates(directory=ADMIN_DIR / "templates")
    templates.env.globals["base_path"] = app.state.base_path
    templates.env.globals["static_version"] = int(datetime.now(timezone.utc).timestamp())
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=ADMIN_DIR / "static"), name="static")
    app.include_router(routes.router, dependencies=[Depends(require_admin)])
    return app
