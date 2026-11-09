from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def admin_home(request: Request) -> HTMLResponse:
    summary = None
    error = None
    try:
        reader = request.app.state.pipeline_reader
        summary = {**reader.summary(), **reader.dashboard_data()}
    except Exception:
        error = "결과 MongoDB를 읽을 수 없습니다. 관리자용 읽기 전용 연결을 확인하세요."
    return request.app.state.templates.TemplateResponse(request, "admin_home.html", {
        "admin_user": getattr(request.state, "admin_user", ""),
        "summary": summary,
        "error": error,
    })
