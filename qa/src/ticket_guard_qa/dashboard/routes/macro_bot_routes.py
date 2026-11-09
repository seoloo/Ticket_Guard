"""B1 봇 프로필 목록 · B2 봇 프로필 편집 · B3 봇 트래픽 모니터 · B4 탐지 성능 리포트 · 봇 설정값은 QA DB에만"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.answer_key.expected_verdicts import plan_virtual_users
from ticket_guard_qa.dashboard.dependencies import (
    get_answer_key_repository,
    get_bot_profile_store,
    get_run_service,
    redirect_to_page,
    render_screen,
)
from ticket_guard_qa.domain.detection_targets import DETECTION_TARGETS, DetectionTarget
from ticket_guard_qa.domain.enums import ActorType, RunStatus, SessionStep, TargetKind, VerdictStage
from ticket_guard_qa.domain.models import ActorProgress, CriterionResult, RunSummary, SessionBehavior, SessionKey
from ticket_guard_qa.macro_bots.behavior_fields import (
    BEHAVIOR_PRESETS,
    PENDING_BEHAVIOR_GROUPS,
    BehaviorInputError,
    behavior_to_dict,
    group_field_specs,
    parse_behavior_form,
)
from ticket_guard_qa.macro_bots.behavior_sampling import build_entry_histogram
from ticket_guard_qa.macro_bots.browser_capture import (
    CAPTURE_FOLDER_NAME,
    CAPTURE_IMAGE_SUFFIXES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    CaptureFrame,
    build_mock_capture_frames,
    load_capture_frames,
)
from ticket_guard_qa.macro_bots.behavior_description import BehaviorLine, describe_behavior
from ticket_guard_qa.macro_bots.bot_catalog import BOT_ROLE_CATALOG, BotRoleInfo, BotTypeInfo, find_bot_type_by_slug
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileLockedError, BotProfileStore
from ticket_guard_qa.macro_bots.bot_profiles import BotProfile, BotProfileRegistry
from ticket_guard_qa.macro_bots.bot_trial_run import TRIAL_SESSION_COUNT, TrialRunResult, run_trial_sessions
from ticket_guard_qa.macro_bots.rule_hit_preview import predict_rule_hits
from ticket_guard_qa.scoring.detection_breakdown import (
    ActorDetectionRow,
    build_actor_detection_rows_from_details,
    classify_verdict,
)
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.test_runs.run_service import RunService
from ticket_guard_qa.test_suites.verdict_accuracy import PLANNED_PROGRESS_KEY, VERDICT_ACCURACY_SUITE_NAME

BOT_SCREEN_CONTEXT = {"active_tab": "qa", "active_subtab": "bots"}
SESSION_STEP_TITLES = {
    SessionStep.ENTERED: "진입",
    SessionStep.SEAT_SELECTED: "좌석",
    SessionStep.CONFIRMED: "확정",
    SessionStep.VERDICT_RECEIVED: "판정",
}
ENTRY_BUCKET_MS = 500  # B3 진입 분포 한 칸
ENTRY_BUCKET_COUNT = 12  # 마지막 칸 = 5.5초 이후 전부
LISTED_SESSION_COUNT_PER_TYPE = 5  # B4 종류별로 보여 줄 놓친 · 오탐 세션 수

router = APIRouter()


@dataclass(frozen=True)
class BotCard:
    profile: BotProfile
    detection_row: ActorDetectionRow | None  # None = 아직 판정 정확도 시험 결과 없음

    @property
    def behavior_lines(self) -> list[BehaviorLine]:
        return describe_behavior(self.profile.behavior)


@dataclass(frozen=True)
class BotRoleSection:
    """B1 구획 하나 · 기준 트래픽 → 탐지 대상 봇 → 평가 전용 봇"""
    number: int
    role_info: BotRoleInfo
    cards: list[BotCard]


def group_cards_by_role(cards: list[BotCard]) -> list[BotRoleSection]:
    sections = []
    for role_info in BOT_ROLE_CATALOG:
        role_cards = [card for card in cards if card.profile.type_info.role is role_info.role]
        if role_cards:
            sections.append(BotRoleSection(len(sections) + 1, role_info, role_cards))
    return sections


@dataclass(frozen=True)
class DetectionTargetCard:
    target: DetectionTarget
    result: CriterionResult


def find_bot_type_or_404(bot_id: str) -> BotTypeInfo:
    type_info = find_bot_type_by_slug(bot_id)
    if type_info is None:
        raise HTTPException(status_code=404, detail="봇 프로필 없음")
    return type_info


def find_summary_or_404(run_service: RunService, run_id: str) -> RunSummary:
    summary = run_service.run_repository.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run 없음")
    return summary


def read_verdict_details(summary: RunSummary | None) -> dict[str, Any]:
    verdict_result = summary.find_suite_result(VERDICT_ACCURACY_SUITE_NAME) if summary else None
    return verdict_result.details if verdict_result else {}


@router.get("/bots", response_class=HTMLResponse)
def show_bot_list(
    request: Request,
    store: BotProfileStore = Depends(get_bot_profile_store),
    run_service: RunService = Depends(get_run_service),
) -> HTMLResponse:
    latest_summary = run_service.run_repository.find_latest_finished_summary_with_suite(VERDICT_ACCURACY_SUITE_NAME)
    rows = build_actor_detection_rows_from_details(read_verdict_details(latest_summary)) if latest_summary else {}
    cards = [BotCard(profile, rows.get(profile.actor_type)) for profile in store.load_current_registry().list_profiles()]
    return render_screen(request, "screen_b1_bot_list.html", {
        **BOT_SCREEN_CONTEXT, "role_sections": group_cards_by_role(cards), "latest_summary": latest_summary,
        "field_groups": group_field_specs(),
    })


def render_bot_settings(
    request: Request,
    store: BotProfileStore,
    type_info: BotTypeInfo,
    behavior: SessionBehavior | None = None,
    trial_result: TrialRunResult | None = None,
    error_message: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    registry = store.load_current_registry()
    current_profile = registry.get_profile(type_info.actor_type)
    shown_behavior = behavior or current_profile.behavior  # 모의 판정 · 오류 때는 입력값 유지
    return render_screen(request, "screen_b2_bot_settings.html", {
        **BOT_SCREEN_CONTEXT,
        "type_info": type_info,
        "profile": current_profile,
        "behavior_values": behavior_to_dict(shown_behavior),
        "human_behavior_values": behavior_to_dict(registry.get_profile(ActorType.HUMAN).behavior),
        "field_groups": group_field_specs(),
        "pending_groups": PENDING_BEHAVIOR_GROUPS,
        "presets": [(preset, behavior_to_dict(preset.behavior)) for preset in BEHAVIOR_PRESETS],
        "rule_previews": predict_rule_hits(shown_behavior, request.app.state.settings.rule_set_version),
        "rule_set_version": request.app.state.settings.rule_set_version,
        "trial_result": trial_result,
        "trial_session_count": TRIAL_SESSION_COUNT,
        "version_history": store.list_version_history(type_info.actor_type),
        "is_edited": shown_behavior != current_profile.behavior,
        "saved_version_number": request.query_params.get("saved_version"),
        "error_message": error_message,
    }, status_code)


@router.get("/bots/{bot_id}/edit", response_class=HTMLResponse)
def show_bot_settings(request: Request, bot_id: str, store: BotProfileStore = Depends(get_bot_profile_store)) -> HTMLResponse:
    return render_bot_settings(request, store, find_bot_type_or_404(bot_id))


@router.post("/bots/{bot_id}/trial", response_class=HTMLResponse)
async def try_bot_settings(
    request: Request,
    bot_id: str,
    store: BotProfileStore = Depends(get_bot_profile_store),
    run_service: RunService = Depends(get_run_service),
) -> HTMLResponse:
    type_info = find_bot_type_or_404(bot_id)
    try:
        behavior = parse_behavior_form(await request.form())
    except BehaviorInputError as error:
        return render_bot_settings(request, store, type_info, error_message=str(error), status_code=400)
    # 항상 가짜 대상 · 실제 시스템에 시험 세션을 남기지 않음 · 같은 값이면 같은 결과
    trial_result = await run_in_threadpool(  # 트래픽 생성기가 자체 이벤트 루프 사용
        run_trial_sessions, build_fake_system_target(run_service.settings.random_seed), behavior
    )
    return render_bot_settings(request, store, type_info, behavior, trial_result)


@router.post("/bots/{bot_id}/versions")
async def save_bot_version(request: Request, bot_id: str, store: BotProfileStore = Depends(get_bot_profile_store)):
    type_info = find_bot_type_or_404(bot_id)
    form = await request.form()
    try:
        behavior = parse_behavior_form(form)
        saved_profile = store.save_new_version(
            type_info.actor_type, behavior, str(form.get("change_note", "")), datetime.now(timezone.utc)
        )
    except (BehaviorInputError, BotProfileLockedError) as error:
        return render_bot_settings(request, store, type_info, error_message=str(error), status_code=400)
    return redirect_to_page(request, f"/bots/{type_info.slug}/edit?saved_version={saved_profile.version_number}")


def build_initial_actor_progress(summary: RunSummary, verdict_details: dict[str, Any]) -> ActorProgress:
    """화면 처음 그릴 때 · 실행 중 = 계획 인원만 · 끝남 = 저장된 표 기준"""
    planned_users = plan_virtual_users(
        summary.run_config.traffic_mix, summary.run_config.virtual_user_count, summary.run_config.random_seed
    )
    rows = build_actor_detection_rows_from_details(verdict_details) if verdict_details else {}
    progress: ActorProgress = {}
    for user in planned_users:
        actor_progress = progress.setdefault(user.actor_type.value, {PLANNED_PROGRESS_KEY: 0})
        actor_progress[PLANNED_PROGRESS_KEY] += 1
    for actor_type, row in rows.items():
        if actor_type.value in progress:
            progress[actor_type.value][SessionStep.ENTERED.value] = row.session_count
            progress[actor_type.value][SessionStep.VERDICT_RECEIVED.value] = row.session_count
    return progress


@router.get("/runs/{run_id}/bots/live", response_class=HTMLResponse)
def show_bot_live(
    request: Request,
    run_id: str,
    run_service: RunService = Depends(get_run_service),
    store: BotProfileStore = Depends(get_bot_profile_store),
) -> HTMLResponse:
    summary = find_summary_or_404(run_service, run_id)
    run_config = summary.run_config
    registry = store.load_registry_for_versions(run_config.bot_version_numbers)  # 실행 당시 버전
    planned_users = plan_virtual_users(run_config.traffic_mix, run_config.virtual_user_count, run_config.random_seed)
    entry_histogram = build_entry_histogram(planned_users, registry, run_config.random_seed, ENTRY_BUCKET_MS, ENTRY_BUCKET_COUNT)
    return render_screen(request, "screen_b3_bot_live.html", {
        **BOT_SCREEN_CONTEXT,
        "summary": summary,
        "is_running": summary.status is RunStatus.RUNNING,
        "has_verdict_suite": VERDICT_ACCURACY_SUITE_NAME in run_config.suite_names,
        "actor_progress": build_initial_actor_progress(summary, read_verdict_details(summary)),
        "planned_progress_key": PLANNED_PROGRESS_KEY,
        "session_step_titles": SESSION_STEP_TITLES,
        "entry_histogram": {actor_type.value: counts for actor_type, counts in entry_histogram.items() if any(counts)},
        "entry_bucket_ms": ENTRY_BUCKET_MS,
        "bot_versions": registry.version_number_by_actor_type(),
        "capture_frames": read_capture_frames(request, summary, registry),
        "is_mock_capture": run_config.target_kind is TargetKind.FAKE,
        "capture_screen_size": (SCREEN_WIDTH, SCREEN_HEIGHT),
    })


def read_capture_frames(request: Request, summary: RunSummary, registry: BotProfileRegistry) -> list[CaptureFrame]:
    """Mock = 봇 C 행동 값으로 만든 프레임 · Live = 브라우저 봇이 저장한 프레임 · 봇 C 0%면 없음"""
    run_config = summary.run_config
    if not run_config.traffic_mix.bot_c_percent:
        return []
    if run_config.target_kind is TargetKind.FAKE:
        return build_mock_capture_frames(registry.get_profile(ActorType.BOT_C).behavior, run_config.random_seed)
    return load_capture_frames(request.app.state.settings.report_output_dir, summary.run_id)



@router.get("/runs/{run_id}/captures/{file_name}")
def show_capture_image(request: Request, run_id: str, file_name: str) -> FileResponse:
    """Live 브라우저 봇 스크린샷 · Run 캡처 폴더 안 파일만"""
    capture_dir = (request.app.state.settings.report_output_dir / CAPTURE_FOLDER_NAME / run_id).resolve()
    image_path = (capture_dir / file_name).resolve()
    if image_path.parent != capture_dir or image_path.suffix.lower() not in CAPTURE_IMAGE_SUFFIXES or not image_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(image_path)

def group_session_keys_by_actor_type(
    session_keys: list[SessionKey], answer_key: dict[SessionKey, ActorType]
) -> dict[ActorType, list[SessionKey]]:
    grouped: dict[ActorType, list[SessionKey]] = defaultdict(list)
    for session_key in session_keys:
        if session_key in answer_key:
            grouped[answer_key[session_key]].append(session_key)
    return grouped


@router.get("/runs/{run_id}/bots", response_class=HTMLResponse)
def show_detection_result(
    request: Request,
    run_id: str,
    run_service: RunService = Depends(get_run_service),
    answer_key_repository: AnswerKeyRepository = Depends(get_answer_key_repository),
):
    summary = find_summary_or_404(run_service, run_id)
    if summary.status is RunStatus.RUNNING:
        return redirect_to_page(request, f"/runs/{run_id}/bots/live")  # 아직 실행 중 → B3
    verdict_details = read_verdict_details(summary)
    answer_key = answer_key_repository.load(run_id) if verdict_details else {}
    result_by_criterion_id = {result.criterion_id: result for result in summary.criterion_results}
    return render_screen(request, "screen_b4_detection_result.html", {
        **BOT_SCREEN_CONTEXT,
        "summary": summary,
        "verdict_details": verdict_details,
        "rows": build_actor_detection_rows_from_details(verdict_details) if verdict_details else {},
        "target_cards": [
            DetectionTargetCard(target, result_by_criterion_id.get(target.criterion_id, CriterionResult(target.criterion_id, None, None)))
            for target in DETECTION_TARGETS
        ],
        "verdict_stages": list(VerdictStage),
        "classify_verdict": classify_verdict,
        "missed_keys_by_actor_type": group_session_keys_by_actor_type(verdict_details.get("missed_bot_session_keys", []), answer_key),
        "false_positive_keys": verdict_details.get("false_positive_session_keys", []),
        "listed_session_count": LISTED_SESSION_COUNT_PER_TYPE,
        "rule_hit_count_by_rule_id": verdict_details.get("rule_hit_count_by_rule_id"),  # TODO(판정 규칙 확정 후): verdict_accuracy가 채움
    })
