"""01 홈 · 통합 검색"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ticket_guard_qa.dashboard.dependencies import get_run_service, redirect_to_page, render_screen
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA
from ticket_guard_qa.test_runs.run_service import RunService

RECENT_RUN_COUNT = 3  # 이어서 하기 3개
VERDICT_SUITE_NAME = "verdict_accuracy"

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def show_home(request: Request, run_service: RunService = Depends(get_run_service)) -> HTMLResponse:
    repository = run_service.run_repository
    recent_summaries = [repository.get_summary(run_id) for run_id in repository.list_recent_run_ids(RECENT_RUN_COUNT)]
    latest_summary = recent_summaries[0] if recent_summaries else None
    latest_verdict_result = latest_summary.find_suite_result(VERDICT_SUITE_NAME) if latest_summary else None
    verdict_details = latest_verdict_result.details if latest_verdict_result else {}
    missed_session_keys = verdict_details.get("missed_bot_session_keys", [])
    return render_screen(request, "screen_01_home.html", {
        "active_tab": "home",
        "latest_summary": latest_summary,
        "criteria_total": len(PASS_CRITERIA),
        "mismatch_count": verdict_details.get("missed_bot_count", 0) + verdict_details.get("false_positive_count", 0)
        if verdict_details else None,
        "first_missed_session_key": missed_session_keys[0] if missed_session_keys else None,
        "active_run_id": run_service.active_run_id,
    })


@router.get("/search")
def search_everything(request: Request, q: str = "", run_service: RunService = Depends(get_run_service)) -> RedirectResponse:
    keyword = q.strip()
    if not keyword:
        return redirect_to_page(request, "/")
    if run_service.run_repository.get_summary(keyword):
        return redirect_to_page(request, f"/runs/{keyword}")
    return redirect_to_page(request, f"/db/sessions/{keyword}")  # 실행 번호가 아니면 세션 · 컬렉션으로
