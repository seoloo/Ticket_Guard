"""01 홈"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ticket_guard_qa.dashboard.dependencies import get_run_service, render_screen
from ticket_guard_qa.test_runs.run_service import RunService

RECENT_RUN_COUNT = 3  # 이어서 하기 3개

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def show_home(request: Request, run_service: RunService = Depends(get_run_service)) -> HTMLResponse:
    recent_summaries = [
        run_service.run_repository.get_summary(run_id)
        for run_id in run_service.run_repository.list_recent_run_ids(RECENT_RUN_COUNT)
    ]
    return render_screen(request, "screen_01_home.html", {
        "active_tab": "home",
        "recent_summaries": recent_summaries,
        "active_run_id": run_service.active_run_id,
    })
