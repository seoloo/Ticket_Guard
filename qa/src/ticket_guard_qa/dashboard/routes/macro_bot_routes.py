"""B1 봇 목록 · B2 봇 설정 · B3 봇 라이브 · B4 탐지 결과"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ticket_guard_qa.dashboard.dependencies import get_bot_profile_registry, render_screen
from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry

router = APIRouter()


@router.get("/bots", response_class=HTMLResponse)
def show_bot_list(request: Request, registry: BotProfileRegistry = Depends(get_bot_profile_registry)) -> HTMLResponse:
    # TODO(판정 정확도 시험 동작 후): 카드마다 마지막 탐지율 · 목표선
    return render_screen(request, "screen_b1_bot_list.html", {
        "active_tab": "qa", "active_subtab": "bots", "profiles": registry.list_profiles(),
    })


@router.get("/bots/{bot_id}/edit", response_class=HTMLResponse)
def show_bot_settings(request: Request, bot_id: str, registry: BotProfileRegistry = Depends(get_bot_profile_registry)) -> HTMLResponse:
    if bot_id.upper() not in ActorType.__members__:
        raise HTTPException(status_code=404, detail="없는 봇")
    # TODO(판정 규칙 확정 후): rule_hit_preview 결과 · 버전 저장
    return render_screen(request, "screen_b2_bot_settings.html", {
        "active_tab": "qa", "active_subtab": "bots", "profile": registry.get_profile(ActorType[bot_id.upper()]),
    })


@router.get("/runs/{run_id}/bots/live", response_class=HTMLResponse)
def show_bot_live(request: Request, run_id: str) -> HTMLResponse:
    # TODO(트래픽 생성기 구현 후): 봇 vs 사람 진입 분포 · 봇 C 화면 캡처
    return render_screen(request, "screen_b3_bot_live.html", {"active_tab": "qa", "active_subtab": "bots", "run_id": run_id})


@router.get("/runs/{run_id}/bots", response_class=HTMLResponse)
def show_detection_result(request: Request, run_id: str) -> HTMLResponse:
    # TODO(판정 정확도 시험 동작 후): build_confusion_matrix · 놓친 세션 → 05
    return render_screen(request, "screen_b4_detection_result.html", {"active_tab": "qa", "active_subtab": "bots", "run_id": run_id})
