"""02 시험 설정 · 03 실행 · 04 결과"""
import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse

from ticket_guard_qa.dashboard.dependencies import (
    get_progress_stream,
    get_run_service,
    redirect_to_page,
    render_screen,
)
from ticket_guard_qa.domain.enums import AlertPolicy, Comparison, RunStatus, TargetKind
from ticket_guard_qa.domain.models import CriterionResult, RunConfig, RunSummary, TrafficMix
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA, PassCriterion
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunAlreadyActiveError, RunService
from ticket_guard_qa.test_suites.suite_registry import list_suites

PROGRESS_POLL_INTERVAL_SEC = 0.5
VIRTUAL_USER_PRESETS = (50, 200, 500)
DURATION_PRESETS_SEC = (120, 300, 600)
DEFAULT_SUITE_NAMES = ("self_check", "event_contract", "verdict_accuracy", "pipeline_latency")
VERDICT_SUITE_NAME = "verdict_accuracy"
TRAFFIC_FIELD_NAMES = ("human_percent", "bot_a_percent", "bot_b_percent", "bot_c_percent", "bot_d_percent")
ALERT_POLICY_TITLES = {AlertPolicy.NEVER: "알림 없음", AlertPolicy.ON_FAILURE: "실패할 때만", AlertPolicy.ALWAYS: "항상"}
NEXT_ACTION_BY_CRITERION_ID = {
    "api_latency": "판정 API 응답 지연 구간 확인 → 백엔드",
    "api_error_rate": "오류 응답 로그 확인 → 백엔드",
    "gold_latency": "Spark 판정 작업 묶음 간격 확인 → 인프라 · 백엔드",
    "recovery_time": "checkpoint · 재시작 절차 확인 → 인프라",
    "bot_abd_detection": "놓친 봇 세션이 안 걸린 규칙 확인 → 판정 규칙 보완 제안",
    "bot_c_detection": "놓친 봇 C 세션의 화면 흐름 확인 → 판정 규칙 보완 제안",
    "human_false_positive": "오탐 세션의 규칙 확인 → 기준 완화 검토",
}

router = APIRouter()


@dataclass(frozen=True)
class CriterionCard:
    criterion: PassCriterion
    result: CriterionResult


@dataclass(frozen=True)
class CriterionComparison:
    criterion: PassCriterion
    previous_value: float
    current_value: float

    @property
    def is_improved(self) -> bool:
        if self.criterion.comparison is Comparison.AT_MOST:
            return self.current_value <= self.previous_value
        return self.current_value >= self.previous_value


def _render_test_setup(
    request: Request, run_service: RunService, run_config: RunConfig, error_message: str = "", status_code: int = 200
) -> HTMLResponse:
    latest_run_ids = run_service.run_repository.list_recent_run_ids(1)
    return render_screen(request, "screen_02_test_setup.html", {
        "active_tab": "qa",
        "run_config": run_config,
        "suites": list_suites(),
        "virtual_user_presets": VIRTUAL_USER_PRESETS,
        "duration_presets_sec": DURATION_PRESETS_SEC,
        "alert_policy_titles": ALERT_POLICY_TITLES,
        "pass_criteria": PASS_CRITERIA,
        "fake_run_duration_sec": run_service.settings.fake_run_duration_sec,
        "active_run_id": run_service.active_run_id,
        "active_run_remaining_sec": run_service.active_run_remaining_sec,
        "latest_run_id": latest_run_ids[0] if latest_run_ids else None,
        "error_message": error_message,
    }, status_code)


@router.get("/runs/new", response_class=HTMLResponse)
def show_test_setup(request: Request, from_run_id: str | None = None, run_service: RunService = Depends(get_run_service)) -> HTMLResponse:
    previous_summary = run_service.run_repository.get_summary(from_run_id) if from_run_id else None
    run_config = previous_summary.run_config if previous_summary else RunConfig(
        target_kind=run_service.settings.target_kind,
        suite_names=DEFAULT_SUITE_NAMES,
        random_seed=run_service.settings.random_seed,
    )
    return _render_test_setup(request, run_service, run_config)


@router.post("/runs")
async def start_test_run(request: Request, run_service: RunService = Depends(get_run_service)):
    form = await request.form()
    suite_names = tuple(form.getlist("suite_names"))
    try:
        traffic_mix = TrafficMix(**{name: int(form.get(name, 0)) for name in TRAFFIC_FIELD_NAMES})
        run_config = RunConfig(
            target_kind=TargetKind(form.get("target_kind", TargetKind.FAKE.value)),
            suite_names=suite_names,
            virtual_user_count=int(form.get("virtual_user_count", 200)),
            duration_sec=int(form.get("duration_sec", 300)),
            traffic_mix=traffic_mix,
            random_seed=run_service.settings.random_seed,
            is_open_burst=form.get("is_open_burst") == "on",
            alert_policy=AlertPolicy(form.get("alert_policy", AlertPolicy.ON_FAILURE.value)),
        )
    except ValueError as error:
        fallback_config = RunConfig(run_service.settings.target_kind, suite_names or DEFAULT_SUITE_NAMES)
        return _render_test_setup(request, run_service, fallback_config, str(error), status_code=400)
    if not suite_names:
        return _render_test_setup(request, run_service, run_config, "시험 묶음을 하나 이상 골라 주세요.", status_code=400)
    try:
        run_id = run_service.start_in_background(run_config)
    except RunAlreadyActiveError as error:
        return _render_test_setup(request, run_service, run_config, str(error), status_code=409)
    return redirect_to_page(request, f"/runs/{run_id}/live")


@router.get("/runs/{run_id}/live", response_class=HTMLResponse)
def show_test_running(request: Request, run_id: str, run_service: RunService = Depends(get_run_service)):
    summary = run_service.run_repository.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="없는 실행 번호")
    if summary.status is not RunStatus.RUNNING:
        return redirect_to_page(request, f"/runs/{run_id}")  # 이미 끝난 실행 → 04
    return render_screen(request, "screen_03_test_running.html", {
        "active_tab": "qa",
        "summary": summary,
        "suite_title_by_name": {suite.suite_name: suite.title for suite in list_suites()},
        "measurement_window_sec": run_service.measurement_window_sec(summary.run_config),
        "threshold_by_metric_name": {criterion.metric_name: criterion.threshold for criterion in PASS_CRITERIA},
    })


@router.get("/runs/{run_id}/events")
async def stream_run_progress(run_id: str, progress_stream: RunProgressStream = Depends(get_progress_stream)) -> StreamingResponse:
    async def generate_server_sent_events() -> AsyncIterator[str]:
        last_sequence_number = 0
        while True:
            for message in progress_stream.read_after(run_id, last_sequence_number):
                last_sequence_number = message.sequence_number
                yield f"data: {json.dumps(message.to_payload(), ensure_ascii=False)}\n\n"
                if message.is_finished:
                    return
            await asyncio.sleep(PROGRESS_POLL_INTERVAL_SEC)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}  # 팀 입구(nginx) 버퍼링 끄기
    return StreamingResponse(generate_server_sent_events(), media_type="text/event-stream", headers=headers)


@router.post("/runs/{run_id}/cancel")
def cancel_test_run(request: Request, run_id: str, run_service: RunService = Depends(get_run_service)) -> RedirectResponse:
    run_service.cancel(run_id)
    return redirect_to_page(request, f"/runs/{run_id}/live")


def build_criterion_comparisons(summary: RunSummary, previous_summary: RunSummary | None) -> list[CriterionComparison]:
    if previous_summary is None:
        return []
    current_values = summary.measured_value_by_criterion_id()
    previous_values = previous_summary.measured_value_by_criterion_id()
    return [
        CriterionComparison(criterion, previous_values[criterion.criterion_id], current_values[criterion.criterion_id])
        for criterion in PASS_CRITERIA
        if criterion.criterion_id in current_values and criterion.criterion_id in previous_values
    ]


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def show_test_result(request: Request, run_id: str, run_service: RunService = Depends(get_run_service)):
    summary = run_service.run_repository.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="없는 실행 번호")
    if summary.status is RunStatus.RUNNING:
        return redirect_to_page(request, f"/runs/{run_id}/live")  # 아직 실행 중 → 03
    result_by_criterion_id = {result.criterion_id: result for result in summary.criterion_results}
    criterion_cards = [
        CriterionCard(criterion, result_by_criterion_id.get(criterion.criterion_id, CriterionResult(criterion.criterion_id, None, None)))
        for criterion in PASS_CRITERIA
    ]
    failed_cards = [card for card in criterion_cards if card.result.is_passed is False]
    verdict_result = summary.find_suite_result(VERDICT_SUITE_NAME)
    return render_screen(request, "screen_04_test_result.html", {
        "active_tab": "qa",
        "summary": summary,
        "criterion_cards": criterion_cards,
        "first_failed_card": failed_cards[0] if failed_cards else None,
        "next_actions": [NEXT_ACTION_BY_CRITERION_ID[card.criterion.criterion_id] for card in failed_cards],
        "verdict_details": verdict_result.details if verdict_result else {},
        "comparisons": build_criterion_comparisons(summary, run_service.run_repository.find_previous_same_config_summary(summary)),
        "suite_title_by_name": {suite.suite_name: suite.title for suite in list_suites()},
        "alert_policy_titles": ALERT_POLICY_TITLES,
    })


@router.get("/runs/{run_id}/report.{report_format}")
def download_report(run_id: str, report_format: str, run_service: RunService = Depends(get_run_service)) -> FileResponse:
    if report_format not in ("html", "json") or run_service.run_repository.get_summary(run_id) is None:
        raise HTTPException(status_code=404, detail="없는 보고서")
    report_path = run_service.settings.report_output_dir / f"{run_id}.{report_format}"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="보고서 파일 없음")
    return FileResponse(report_path)
