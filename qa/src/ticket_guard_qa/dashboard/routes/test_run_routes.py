"""02 시험 설정 · 03 실행 · 04 결과"""
import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ticket_guard_qa.dashboard.dependencies import get_progress_stream, get_run_service, render_screen
from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunAlreadyActiveError, RunService
from ticket_guard_qa.test_suites.suite_registry import list_suites

PROGRESS_POLL_INTERVAL_SEC = 0.5

router = APIRouter()


def _render_test_setup(request: Request, run_service: RunService, error_message: str = "", status_code: int = 200) -> HTMLResponse:
    return render_screen(request, "screen_02_test_setup.html", {
        "active_tab": "qa",
        "suites": list_suites(),
        "target_kinds": list(TargetKind),
        "pass_criteria": PASS_CRITERIA,
        "active_run_id": run_service.active_run_id,
        "error_message": error_message,
    }, status_code)


@router.get("/runs/new", response_class=HTMLResponse)
def show_test_setup(request: Request, run_service: RunService = Depends(get_run_service)) -> HTMLResponse:
    return _render_test_setup(request, run_service)


@router.post("/runs")
def start_test_run(
    request: Request,
    suite_names: list[str] = Form(...),
    target_kind: TargetKind = Form(TargetKind.FAKE),
    virtual_user_count: int = Form(200),
    duration_sec: int = Form(300),
    run_service: RunService = Depends(get_run_service),
):
    run_config = RunConfig(
        target_kind=target_kind,
        suite_names=tuple(suite_names),
        virtual_user_count=virtual_user_count,
        duration_sec=duration_sec,
        random_seed=run_service.settings.random_seed,
    )
    try:
        run_id = run_service.start_in_background(run_config)
    except RunAlreadyActiveError as error:
        return _render_test_setup(request, run_service, str(error), status_code=409)
    return RedirectResponse(f"/runs/{run_id}/live", status_code=303)


@router.get("/runs/{run_id}/live", response_class=HTMLResponse)
def show_test_running(request: Request, run_id: str) -> HTMLResponse:
    return render_screen(request, "screen_03_test_running.html", {"active_tab": "qa", "run_id": run_id})


@router.get("/runs/{run_id}/events")
async def stream_run_progress(run_id: str, progress_stream: RunProgressStream = Depends(get_progress_stream)) -> StreamingResponse:
    async def generate_server_sent_events() -> AsyncIterator[str]:
        last_sequence_number = 0
        while True:
            for message in progress_stream.read_after(run_id, last_sequence_number):
                last_sequence_number = message.sequence_number
                payload = {"text": message.text, "is_finished": message.is_finished}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if message.is_finished:
                    return
            await asyncio.sleep(PROGRESS_POLL_INTERVAL_SEC)

    return StreamingResponse(generate_server_sent_events(), media_type="text/event-stream")


@router.post("/runs/{run_id}/cancel")
def cancel_test_run(run_id: str, run_service: RunService = Depends(get_run_service)) -> RedirectResponse:
    run_service.cancel(run_id)
    return RedirectResponse(f"/runs/{run_id}/live", status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def show_test_result(request: Request, run_id: str, run_service: RunService = Depends(get_run_service)) -> HTMLResponse:
    summary = run_service.run_repository.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="없는 실행 번호")
    title_by_criterion_id = {criterion.criterion_id: criterion.title for criterion in PASS_CRITERIA}
    return render_screen(request, "screen_04_test_result.html", {
        "active_tab": "qa",
        "summary": summary,
        "criteria_total": len(PASS_CRITERIA),
        "title_by_criterion_id": title_by_criterion_id,
    })
