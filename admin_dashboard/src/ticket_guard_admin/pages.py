"""관리자 화면 렌더링 · 샘플 시안과 실제 DB 조회 화면 분리"""
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ticket_guard_admin.preview_data import build_preview_data
from ticket_guard_admin.mongo_reader import AdminMongoReader
from pymongo.errors import PyMongoError

ADMIN_DASHBOARD_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=ADMIN_DASHBOARD_DIR / "templates")


def render_db_preview(request: Request, run_id: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "screen_05_admin_dashboard.html", {
        "base_path": request.app.state.base_path,
        "admin_user": getattr(request.state, "admin_user", ""),
        "run_id": run_id,
        **build_preview_data(),
    })


def render_live_dashboard(request: Request, mongo_uri: str) -> HTMLResponse:
    params = request.query_params
    context = {"base_path": request.app.state.base_path,
               "admin_user": getattr(request.state, "admin_user", ""), "error": None,
               "period": params.get("period", "all"), "show": params.get("show", ""),
               "schedule": params.get("schedule", ""), "data_kind": params.get("data", "all")}
    try:
        context.update(AdminMongoReader(mongo_uri).read_dashboard(
            context["period"], context["show"], context["schedule"], context["data_kind"]))
    except (PyMongoError, ValueError):
        context["error"] = "DB 조회 실패 · 관리자 전용 연결 설정과 읽기 권한 확인 필요"
    response = templates.TemplateResponse(request, "screen_05_live_dashboard.html", context)
    response.headers["Cache-Control"] = "no-store"
    return response
