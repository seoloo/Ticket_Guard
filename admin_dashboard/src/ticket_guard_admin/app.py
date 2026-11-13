"""
[홍석환] 관리자 전용 앱과 인증된 화면 경로
공개 지표·기존 이벤트 조회·시안을 분리하며 QA 저장소를 초기화하지 않는다.
"""
from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from ticket_guard_admin.pages import ADMIN_DASHBOARD_DIR, render_live_dashboard
from ticket_guard_admin.dependencies import require_admin
from ticket_guard_admin.settings import AdminSettings
from ticket_guard_admin.user_flow.pages import render_published_dashboard


def create_admin_dashboard_app(settings: AdminSettings | None = None) -> FastAPI:
    app = FastAPI(title="TicketGuard 관리자 대시보드")
    app.state.admin_settings = settings or AdminSettings()
    app.state.base_path = app.state.admin_settings.base_path.rstrip("/")
    app.mount("/admin-static", StaticFiles(directory=ADMIN_DASHBOARD_DIR / "static"), name="admin-static")

    @app.get("/", dependencies=[Depends(require_admin)])
    def dashboard(request: Request):
        return render_published_dashboard(request, app.state.admin_settings.mongo_uri)

    @app.get("/db", dependencies=[Depends(require_admin)])
    def legacy_dashboard(request: Request):
        return render_live_dashboard(request, app.state.admin_settings.mongo_uri)

    @app.get("/preview", dependencies=[Depends(require_admin)])
    def preview(request: Request, run_id: str | None = None):
        from ticket_guard_admin.pages import render_db_preview

        return render_db_preview(request, run_id)

    return app
