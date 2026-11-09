"""05 DB 대시보드 · 정답은 QA DB · 판정은 시스템 DB(읽기 전용) · 시스템 쪽에 쓰지 않음"""
from datetime import datetime, timezone
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ticket_guard_qa.dashboard.dependencies import render_screen
from ticket_guard_qa.system_targets.live_mongo_reader import LiveMongoPipelineReader

SYSTEM_DATABASE_NOT_READY_MESSAGE = "시스템 MongoDB 미연결 · AGENTS.md 5장"

router = APIRouter()


@router.get("/db", response_class=HTMLResponse)
def show_db_dashboard(request: Request, run_id: str | None = None) -> HTMLResponse:
    settings = request.app.state.settings
    summary = None
    error_message = None
    if settings.system_mongo_uri:
        try:
            reader = LiveMongoPipelineReader(settings.system_mongo_uri)
            summary = {**reader.summary(), **reader.dashboard_data()}
        except Exception:
            error_message = "시스템 MongoDB를 읽을 수 없습니다. 연결 설정과 read-only 권한을 확인하세요."
    return render_screen(request, "screen_05_db_dashboard.html", {
        "active_tab": "db",
        "run_id": run_id,
        "session_key": None,
        "not_ready_message": error_message or (None if summary else SYSTEM_DATABASE_NOT_READY_MESSAGE),
        "pipeline_summary": summary,
    })


@router.post("/db/reviews/{user_id}", response_class=HTMLResponse)
def save_review(request: Request, user_id: str, status: str = Form("unreviewed"), memo: str = Form("")) -> HTMLResponse:
    session = request.app.state.qa_session_factory()
    try:
        from ticket_guard_qa.qa_database.tables import DashboardReviewRecord
        record = session.get(DashboardReviewRecord, user_id) or DashboardReviewRecord(user_id=user_id)
        record.status, record.memo = status[:30], memo[:4000]
        record.reviewer = getattr(request.state, "admin_user", "")[:120]
        record.reviewed_at = datetime.now(timezone.utc)
        session.add(record)
        session.commit()
    finally:
        session.close()
    return show_db_dashboard(request)


@router.get("/db/sessions/{session_key}", response_class=HTMLResponse)
def show_session_trace(request: Request, session_key: str, run_id: str | None = None) -> HTMLResponse:
    # TODO(MongoDB 연결 후): QA 정답 VS 시스템 판정 · 예매 단계별 흐름 · DB 기록
    return render_screen(request, "screen_05_db_dashboard.html", {
        "active_tab": "db",
        "run_id": run_id,
        "session_key": session_key,
        "not_ready_message": SYSTEM_DATABASE_NOT_READY_MESSAGE,
    })
