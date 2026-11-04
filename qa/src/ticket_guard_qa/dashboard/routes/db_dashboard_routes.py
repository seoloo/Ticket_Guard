"""05 DB 대시보드 · 정답은 QA DB · 판정은 시스템 DB(읽기 전용) · 시스템 쪽에 쓰지 않음"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ticket_guard_qa.dashboard.dependencies import render_screen

SYSTEM_DATABASE_NOT_READY_MESSAGE = "시스템 MongoDB 미연결 · AGENTS.md 5장"

router = APIRouter()


@router.get("/db", response_class=HTMLResponse)
def show_db_dashboard(request: Request, run_id: str | None = None) -> HTMLResponse:
    # TODO(MongoDB 연결 후): live_mongo_reader로 컬렉션 건수 · 정답과 다른 세션 목록
    return render_screen(request, "screen_05_db_dashboard.html", {
        "active_tab": "db",
        "run_id": run_id,
        "session_key": None,
        "not_ready_message": SYSTEM_DATABASE_NOT_READY_MESSAGE,
    })


@router.get("/db/sessions/{session_key}", response_class=HTMLResponse)
def show_session_trace(request: Request, session_key: str, run_id: str | None = None) -> HTMLResponse:
    # TODO(MongoDB 연결 후): QA 정답 VS 시스템 판정 · 예매 단계별 흐름 · DB 기록
    return render_screen(request, "screen_05_db_dashboard.html", {
        "active_tab": "db",
        "run_id": run_id,
        "session_key": session_key,
        "not_ready_message": SYSTEM_DATABASE_NOT_READY_MESSAGE,
    })
