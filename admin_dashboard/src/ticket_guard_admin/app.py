"""관리자 전용 앱 · QA DB와 시험 실행 초기화 없음 · 팀 게이트웨이 전용"""
from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from ticket_guard_admin.pages import ADMIN_DASHBOARD_DIR, render_live_dashboard
from ticket_guard_admin.dependencies import require_admin
from ticket_guard_admin.settings import AdminSettings


def create_admin_dashboard_app(settings: AdminSettings | None = None) -> FastAPI:
    app = FastAPI(title="TicketGuard 관리자 대시보드")
    app.state.admin_settings = settings or AdminSettings()
    app.state.base_path = app.state.admin_settings.base_path.rstrip("/")
    app.mount("/admin-static", StaticFiles(directory=ADMIN_DASHBOARD_DIR / "static"), name="admin-static")

    @app.get("/", dependencies=[Depends(require_admin)])
    @app.get("/db", dependencies=[Depends(require_admin)])
    def dashboard(request: Request):
        return render_live_dashboard(request, app.state.admin_settings.mongo_uri)

    @app.get("/preview", dependencies=[Depends(require_admin)])
    def preview(request: Request, run_id: str | None = None):
        from ticket_guard_admin.pages import render_db_preview

        return render_db_preview(request, run_id)

    return app
