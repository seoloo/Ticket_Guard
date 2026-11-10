"""02 시험 설정 · 03 실행 · 04 결과"""
import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from ticket_guard_qa.dashboard.criterion_status import STATUS_TITLES, build_criterion_rows, count_statuses
from ticket_guard_qa.dashboard.suite_result_view import build_suite_result_view
from ticket_guard_qa.dashboard.dependencies import (
    get_progress_stream,
    get_run_service,
    redirect_to_page,
    render_screen,
)
from ticket_guard_qa.domain.enums import AlertPolicy, Comparison, RunStatus, TargetKind
from ticket_guard_qa.domain.models import LEGACY_TRAFFIC_FIELD_TO_ACTOR, CriterionResult, RunConfig, RunSummary, TrafficMix
from ticket_guard_qa.macro_bots.bot_catalog import BotTypeInfo, list_bot_types
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA, PassCriterion
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunAlreadyActiveError, RunDeleteError, RunService
from ticket_guard_qa.test_suites.suite_registry import get_suite, list_suites
from ticket_guard_qa.test_suites.verdict_accuracy import VERDICT_ACCURACY_SUITE_NAME

PROGRESS_POLL_INTERVAL_SEC = 0.5
RESULT_LIST_LIMIT = 50  # 테스트 결과 목록 · 최신 Run
RUN_STATUS_FILTERS = {"PASSED": "PASS", "FAILED": "FAIL", "RUNNING": "진행 중", "ERROR": "ERROR", "CANCELLED": "중지"}
VIRTUAL_USER_PRESETS = (50, 200, 500)
DURATION_PRESETS_SEC = (120, 300, 600)  # Live · 트래픽 Suite 1개 최대 시간
AUTO_TIME_LIMIT_VALUE = 0  # 자동 · 예상 시간 기준
ENTRY_MODE_BURST, ENTRY_MODE_WAVE = "burst", "wave"  # 접속 방식 · 한 번에 전원 진입 · 나눠서 진입
DEFAULT_WAVE_SIZE = 40  # 나눠서 진입 처음 값
TRAFFIC_FIELD_PREFIX = "percent_"  # 폼 이름 · percent_HUMAN · percent_BOT_E


def list_traffic_types(run_service: RunService) -> list[BotTypeInfo]:
    """02 트래픽 구성 칸 · 평가 전용 · 작성 중 제외 · QA DB 추가 유형 포함"""
    run_service.bot_profile_store.bot_type_store.refresh_catalog()
    return [info for info in list_bot_types() if info.is_in_traffic_mix]


def parse_traffic_mix(form, traffic_types: list[BotTypeInfo]) -> TrafficMix:
    """새 이름(percent_유형) · 이전 이름(human_percent 등) 둘 다"""
    legacy_name_by_actor = {actor: name for name, actor in LEGACY_TRAFFIC_FIELD_TO_ACTOR.items()}
    percents = {}
    for info in traffic_types:
        actor = info.actor_type.value
        raw_value = form.get(f"{TRAFFIC_FIELD_PREFIX}{actor}", form.get(legacy_name_by_actor.get(actor, ""), 0))
        percents[actor] = int(raw_value or 0)
    return TrafficMix(percents)
ALERT_POLICY_TITLES = {AlertPolicy.NEVER: "알림 없음", AlertPolicy.ON_FAILURE: "FAIL 시 알림", AlertPolicy.ALWAYS: "항상 알림"}
NEXT_ACTION_BY_CRITERION_ID = {
    "api_latency": "판정 API 지연 구간 분석 → 백엔드",
    "api_error_rate": "오류 응답 로그 분석 → 백엔드",
    "gold_latency": "Spark 판정 배치 간격 점검 → 인프라 · 백엔드",
    "recovery_time": "checkpoint · 재기동 절차 점검 → 인프라",
    "bot_abd_detection": "미탐 세션 미적용 룰 분석 → 판정 룰 보완 제안",
    "bot_c_detection": "봇 C 미탐 세션 페이지 흐름 분석 → 판정 룰 보완 제안",
    "human_false_positive": "오탐 세션 적용 룰 분석 → 임계값 완화 검토",
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
        "traffic_types": list_traffic_types(run_service),
        "suites": list_suites(),
        "virtual_user_presets": VIRTUAL_USER_PRESETS,
        "duration_presets_sec": DURATION_PRESETS_SEC,
        "auto_time_limit_value": AUTO_TIME_LIMIT_VALUE,
        "default_wave_size": DEFAULT_WAVE_SIZE,
        "suite_title_by_name": {suite.suite_name: suite.title for suite in list_suites()},
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
        suite_names=(),  # 처음 화면 · 선택 없음
        duration_sec=AUTO_TIME_LIMIT_VALUE,
        random_seed=run_service.settings.random_seed,
    )
    return _render_test_setup(request, run_service, run_config)


def parse_wave_size(form, virtual_user_count: int) -> int:
    """접속 방식 · 한 번에 전원 = 0 · 나눠서 진입 = 회차당 인원 1 ~ VU 수"""
    if form.get("entry_mode", ENTRY_MODE_BURST) != ENTRY_MODE_WAVE:
        return 0
    wave_size = int(form.get("wave_size") or 0)
    if not 1 <= wave_size <= virtual_user_count:
        raise ValueError(f"회차당 인원 1 ~ {virtual_user_count}명 사이 입력 필요")
    return wave_size


def parse_run_config(form, run_service: RunService) -> RunConfig:
    """02 폼 → Run 설정 · 최대 시간 0 = 자동 · 잘못된 값 = ValueError"""
    virtual_user_count = int(form.get("virtual_user_count", 200))
    wave_size = parse_wave_size(form, virtual_user_count)
    return RunConfig(
        target_kind=TargetKind(form.get("target_kind", TargetKind.FAKE.value)),
        suite_names=tuple(form.getlist("suite_names")),
        virtual_user_count=virtual_user_count,
        duration_sec=max(int(form.get("duration_sec", AUTO_TIME_LIMIT_VALUE) or AUTO_TIME_LIMIT_VALUE), 0),
        traffic_mix=parse_traffic_mix(form, list_traffic_types(run_service)),
        random_seed=run_service.settings.random_seed,
        is_open_burst=wave_size == 0,
        alert_policy=AlertPolicy(form.get("alert_policy", AlertPolicy.ON_FAILURE.value)),
        wave_size=wave_size,
    )


@router.post("/runs/estimate")
async def estimate_test_run(request: Request, run_service: RunService = Depends(get_run_service)) -> JSONResponse:
    """02 Run 요약 · Live 예상 소요 · 입력이 바뀔 때마다 · Mock = 흉내 시간"""
    form = await request.form()
    try:
        run_config = parse_run_config(form, run_service)
    except ValueError:
        return JSONResponse({"error": "입력 값 오류"}, status_code=400)
    estimate = run_service.estimate_run(run_config)
    if estimate is None:
        return JSONResponse({"total_sec": run_service.settings.fake_run_duration_sec, "suites": []})
    return JSONResponse(estimate.to_payload())


@router.post("/runs")
async def start_test_run(request: Request, run_service: RunService = Depends(get_run_service)):
    form = await request.form()
    suite_names = tuple(form.getlist("suite_names"))
    try:
        run_config = parse_run_config(form, run_service)
    except ValueError as error:
        fallback_config = RunConfig(run_service.settings.target_kind, suite_names)
        return _render_test_setup(request, run_service, fallback_config, str(error), status_code=400)
    if not suite_names:
        return _render_test_setup(request, run_service, run_config, "Suite 미선택 · 1개 이상 선택 필요", status_code=400)
    try:
        run_id = run_service.start_in_background(run_config)
    except RunAlreadyActiveError as error:
        return _render_test_setup(request, run_service, run_config, str(error), status_code=409)
    return redirect_to_page(request, f"/runs/{run_id}/live")


@router.get("/runs/{run_id}/live", response_class=HTMLResponse)
def show_test_running(request: Request, run_id: str, run_service: RunService = Depends(get_run_service)):
    summary = run_service.run_repository.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run 없음")
    if summary.status is not RunStatus.RUNNING:
        return redirect_to_page(request, f"/runs/{run_id}")  # 이미 끝난 실행 → 04
    return render_screen(request, "screen_03_test_running.html", {
        "active_tab": "qa",
        "summary": summary,
        "run_suites": [get_suite(suite_name) for suite_name in summary.run_config.suite_names],  # 실행 순서
        "measurement_window_sec": run_service.measurement_window_sec(summary.run_config, run_id),
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


@router.get("/runs", response_class=HTMLResponse)
def show_test_results(request: Request, status: str = "", deleted: str = "", run_service: RunService = Depends(get_run_service)) -> HTMLResponse:
    """테스트 결과 · Run 기록 최신순 · 판정 거르기 · 04 리포트로 이동"""
    return _render_result_list(request, run_service, status, f"Run {deleted[-11:]} 삭제 완료" if deleted else "")


@router.post("/runs/{run_id}/delete")
async def delete_test_run(request: Request, run_id: str, run_service: RunService = Depends(get_run_service)):
    """Run 기록 · 정답표 · 보고서 삭제 · 진행 중 Run 거절 · 되돌릴 수 없음"""
    form = await request.form()
    status = str(form.get("status", ""))
    try:
        run_service.delete_run(run_id)
    except RunDeleteError as error:
        return _render_result_list(request, run_service, status, error_message=str(error), status_code=409)
    query = {'status': status, 'deleted': run_id} if status else {'deleted': run_id}  # 거르기 유지
    return redirect_to_page(request, f"/runs?{urlencode(query)}")


def _render_result_list(
    request: Request, run_service: RunService, status: str, notice: str = "", error_message: str = "", status_code: int = 200
) -> HTMLResponse:
    repository = run_service.run_repository
    summaries = [summary for run_id in repository.list_recent_run_ids(RESULT_LIST_LIMIT)
                 if (summary := repository.get_summary(run_id)) is not None]
    selected_status = status if status in RUN_STATUS_FILTERS else ""
    shown_summaries = [summary for summary in summaries if not selected_status or summary.status.value == selected_status]
    return render_screen(request, "screen_04_result_list.html", {
        "active_tab": "qa",
        "active_subtab": "results",
        "summaries": shown_summaries,
        "delete_items_by_run_id": {summary.run_id: run_service.list_delete_items(summary)
                                   for summary in shown_summaries if summary.status is not RunStatus.RUNNING},
        "status_counts": {value: sum(summary.status.value == value for summary in summaries) for value in RUN_STATUS_FILTERS},
        "total_count": len(summaries),
        "selected_status": selected_status,
        "status_titles": RUN_STATUS_FILTERS,
        "criteria_total": len(PASS_CRITERIA),
        "suite_title_by_name": {suite.suite_name: suite.title for suite in list_suites()},
        "active_run_id": run_service.active_run_id,
        "notice": notice,
        "error_message": error_message,
    }, status_code)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def show_test_result(request: Request, run_id: str, run_service: RunService = Depends(get_run_service)):
    summary = run_service.run_repository.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run 없음")
    if summary.status is RunStatus.RUNNING:
        return redirect_to_page(request, f"/runs/{run_id}/live")  # 아직 실행 중 → 03
    result_by_criterion_id = {result.criterion_id: result for result in summary.criterion_results}
    criterion_cards = [
        CriterionCard(criterion, result_by_criterion_id.get(criterion.criterion_id, CriterionResult(criterion.criterion_id, None, None)))
        for criterion in PASS_CRITERIA
    ]
    failed_cards = [card for card in criterion_cards if card.result.is_passed is False]
    verdict_result = summary.find_suite_result(VERDICT_ACCURACY_SUITE_NAME)
    suite_title_by_name = {suite.suite_name: suite.title for suite in list_suites()}
    criterion_rows = build_criterion_rows(summary, suite_title_by_name)
    return render_screen(request, "screen_04_test_result.html", {
        "active_tab": "qa",
        "active_subtab": "results",
        "summary": summary,
        "criterion_cards": criterion_cards,
        "criterion_rows": criterion_rows,
        "criterion_status_counts": count_statuses(criterion_rows),
        "criterion_status_titles": STATUS_TITLES,
        "first_failed_card": failed_cards[0] if failed_cards else None,
        "next_actions": [NEXT_ACTION_BY_CRITERION_ID[card.criterion.criterion_id] for card in failed_cards],
        "verdict_details": verdict_result.details if verdict_result else {},
        "comparisons": build_criterion_comparisons(summary, run_service.run_repository.find_previous_same_config_summary(summary)),
        "suite_title_by_name": suite_title_by_name,
        "suite_views": [(result, build_suite_result_view(result)) for result in summary.suite_results],
        "alert_policy_titles": ALERT_POLICY_TITLES,
    })


@router.get("/runs/{run_id}/report.{report_format}")
def download_report(run_id: str, report_format: str, run_service: RunService = Depends(get_run_service)) -> FileResponse:
    if report_format not in ("html", "json") or run_service.run_repository.get_summary(run_id) is None:
        raise HTTPException(status_code=404, detail="리포트 없음")
    report_path = run_service.settings.report_output_dir / f"{run_id}.{report_format}"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="리포트 파일 없음")
    return FileResponse(report_path)
