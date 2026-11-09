"""B5 새 봇 추가 · ① 시작 봇 → ② 이름 · 분류 → ③ 예매 중 행동 → ④ 탐지 흔적 · 합격 기준 → ⑤ 모의 판정 · 저장 · QA DB에만"""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse

from ticket_guard_qa.dashboard.dependencies import get_bot_profile_store, get_run_service, redirect_to_page, render_screen
from ticket_guard_qa.domain.detection_targets import BOT_SELECTABLE_TARGET_IDS, DETECTION_TARGETS
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.macro_bots.behavior_description import describe_behavior
from ticket_guard_qa.macro_bots.behavior_fields import BehaviorInputError, behavior_to_dict, group_field_specs, parse_behavior_form
from ticket_guard_qa.macro_bots.bot_catalog import (
    BOT_CATEGORIES,
    HTTP_TRAFFIC,
    BotStatus,
    BotTypeInfo,
    find_bot_type_by_slug,
    list_bot_types,
)
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileStore
from ticket_guard_qa.macro_bots.bot_trial_run import TRIAL_SESSION_COUNT, TrialRunResult, run_trial_sessions
from ticket_guard_qa.macro_bots.bot_type_store import MAX_DETECTION_SIGNAL_COUNT, TRAFFIC_CHANNELS, BotTypeInputError
from ticket_guard_qa.macro_bots.rule_hit_preview import predict_rule_hits
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.test_runs.run_service import RunService

BOT_SCREEN_CONTEXT = {"active_tab": "qa", "active_subtab": "bots"}
NO_TARGET_VALUE = "none"  # 합격 기준 없음 · 결과 공개만
FIRST_STEP, LAST_STEP = 1, 5

router = APIRouter()


@dataclass(frozen=True)
class SetupStep:
    number: int
    title: str


SETUP_STEPS: tuple[SetupStep, ...] = (
    SetupStep(1, "시작 봇 선택"),
    SetupStep(2, "이름 · 수법 분류"),
    SetupStep(3, "예매 중 행동"),
    SetupStep(4, "탐지 흔적 · 합격 기준"),
    SetupStep(5, "모의 판정 · 저장"),
)


def list_base_candidates() -> list[BotTypeInfo]:
    """복사할 수 있는 봇 · 평가 전용 · 작성 중 제외"""
    return [info for info in list_bot_types() if not info.is_locked and info.status is not BotStatus.DRAFT]


def find_custom_bot_or_404(store: BotProfileStore, bot_id: str) -> BotTypeInfo:
    store.bot_type_store.refresh_catalog()
    info = find_bot_type_by_slug(bot_id)
    if info is None or not info.is_custom:
        raise HTTPException(status_code=404, detail="추가한 봇 유형 없음")
    return info


def summarize_step_values(info: BotTypeInfo, base_name: str) -> dict[int, str]:
    """단계 표시줄 · 끝난 단계에 고른 값"""
    return {1: f"{base_name} 복사", 2: f"{info.type_name} · {info.category.title}" if info.purpose else ""}


def render_setup(
    request: Request, store: BotProfileStore, step: int, info: BotTypeInfo | None = None,
    behavior: SessionBehavior | None = None, trial_result: TrialRunResult | None = None,
    error_message: str = "", status_code: int = 200,
) -> HTMLResponse:
    shown_behavior = behavior or (store.load_current_registry().get_profile(info.actor_type).behavior if info else None)
    base_name = ""
    if info is not None:
        document = store.bot_type_store.find_document(info.actor_type) or {}
        base_info = next((candidate for candidate in list_bot_types() if candidate.actor_type == document.get("base_actor_type")), None)
        base_name = base_info.type_name if base_info else ""
    rule_set_version = request.app.state.settings.rule_set_version
    return render_screen(request, "screen_b5_bot_add.html", {
        **BOT_SCREEN_CONTEXT,
        "steps": SETUP_STEPS,
        "step": step,
        "info": info,
        "step_values": summarize_step_values(info, base_name) if info else {},
        "base_candidates": list_base_candidates(),
        "categories": [category for category in BOT_CATEGORIES if category.is_selectable],
        "traffic_channels": TRAFFIC_CHANNELS,
        "field_groups": group_field_specs(),
        "behavior_values": behavior_to_dict(shown_behavior) if shown_behavior else {},
        "behavior_lines": describe_behavior(shown_behavior) if shown_behavior else [],
        "rule_previews": predict_rule_hits(shown_behavior, rule_set_version) if shown_behavior else [],
        "rule_set_version": rule_set_version,
        "detection_targets": [target for target in DETECTION_TARGETS if target.criterion_id in BOT_SELECTABLE_TARGET_IDS],
        "no_target_value": NO_TARGET_VALUE,
        "signal_slots": MAX_DETECTION_SIGNAL_COUNT,
        "trial_result": trial_result,
        "trial_session_count": TRIAL_SESSION_COUNT,
        "error_message": error_message,
    }, status_code)


@router.get("/bots/new", response_class=HTMLResponse)
def show_new_bot(request: Request, store: BotProfileStore = Depends(get_bot_profile_store)) -> HTMLResponse:
    store.bot_type_store.refresh_catalog()
    return render_setup(request, store, FIRST_STEP)


@router.post("/bots/new")
async def create_new_bot(request: Request, store: BotProfileStore = Depends(get_bot_profile_store)):
    form = await request.form()
    registry = store.load_current_registry()
    base_info = next((info for info in list_base_candidates() if info.slug == str(form.get("base_bot", ""))), None)
    if base_info is None:
        return render_setup(request, store, FIRST_STEP, error_message="시작 봇 미선택 · 1개 선택 필요", status_code=400)
    created = store.bot_type_store.create_draft(base_info, registry.get_profile(base_info.actor_type).behavior,
                                                datetime.now(timezone.utc))
    return redirect_to_page(request, f"/bots/{created.slug}/setup/2")


@router.get("/bots/{bot_id}/setup/{step}", response_class=HTMLResponse)
def show_setup_step(request: Request, bot_id: str, step: int, store: BotProfileStore = Depends(get_bot_profile_store)):
    info = find_custom_bot_or_404(store, bot_id)
    if not FIRST_STEP < step <= LAST_STEP:
        raise HTTPException(status_code=404, detail="단계 없음")
    if info.status is not BotStatus.DRAFT:  # 검증 중부터는 B2에서 버전으로 수정
        return redirect_to_page(request, f"/bots/{info.slug}/edit")
    return render_setup(request, store, step, info)


@router.post("/bots/{bot_id}/setup/{step}", response_class=HTMLResponse)
async def save_setup_step(
    request: Request, bot_id: str, step: int,
    store: BotProfileStore = Depends(get_bot_profile_store), run_service: RunService = Depends(get_run_service),
):
    info = find_custom_bot_or_404(store, bot_id)
    if info.status is not BotStatus.DRAFT:
        return redirect_to_page(request, f"/bots/{info.slug}/edit")
    form = await request.form()
    now = datetime.now(timezone.utc)
    type_store = store.bot_type_store
    try:
        if step == 2:
            type_store.update_identity(info.actor_type, str(form.get("display_name", "")), str(form.get("purpose", "")),
                                       str(form.get("category_id", "")), now, str(form.get("traffic_channel", HTTP_TRAFFIC)))
        elif step == 3:
            behavior = parse_behavior_form(form)
            if form.get("action") == "preview":  # 문장 미리보기만 · 저장 안 함
                return render_setup(request, store, 3, info, behavior)
            type_store.update_initial_behavior(info.actor_type, behavior, now)
        elif step == 4:
            target_value = str(form.get("detection_target_id", ""))
            type_store.update_detection(info.actor_type, list(form.getlist("detection_signals")),
                                        None if target_value == NO_TARGET_VALUE else target_value, BOT_SELECTABLE_TARGET_IDS, now)
        elif step == 5:
            if form.get("action") == "trial":  # 항상 가짜 대상 · 실제 시스템에 시험 세션을 남기지 않음
                behavior = store.load_current_registry().get_profile(info.actor_type).behavior
                trial_result = await run_in_threadpool(
                    run_trial_sessions, build_fake_system_target(run_service.settings.random_seed), behavior
                )
                return render_setup(request, store, 5, info, trial_result=trial_result)
            saved = type_store.change_status(info.actor_type, BotStatus.REVIEW, now)
            return redirect_to_page(request, f"/bots?bot={saved.slug}")
        else:
            raise HTTPException(status_code=404, detail="단계 없음")
    except (BotTypeInputError, BehaviorInputError) as error:
        refreshed = find_custom_bot_or_404(store, bot_id)
        return render_setup(request, store, step, refreshed, error_message=str(error), status_code=400)
    return redirect_to_page(request, f"/bots/{info.slug}/setup/{step + 1}")


@router.post("/bots/{bot_id}/status")
async def change_bot_status(request: Request, bot_id: str, store: BotProfileStore = Depends(get_bot_profile_store)):
    """검증 중 → 사용 중 · 사용 중 → 검증 중 · 추가한 유형만"""
    info = find_custom_bot_or_404(store, bot_id)
    form = await request.form()
    try:
        status = BotStatus(str(form.get("status", "")))
        if status is BotStatus.DRAFT:
            raise ValueError
        store.bot_type_store.change_status(info.actor_type, status, datetime.now(timezone.utc))
    except (ValueError, BotTypeInputError):
        raise HTTPException(status_code=400, detail="상태 변경 불가") from None
    return redirect_to_page(request, f"/bots?bot={info.slug}")
