"""테스트 케이스 · Ground Truth 탭 · 예외 코드 사례 · 이벤트 계약 사례 · Run별 정답표 조회 · QA DB 읽기만"""
from collections import Counter

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ticket_guard_qa.dashboard.dependencies import render_screen
from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.macro_bots.bot_catalog import get_bot_type_info, list_actor_types
from ticket_guard_qa.test_suites.event_contract import ACTION_ENDPOINT, BROWSER_EVENTS_ENDPOINT, load_contract_cases
from ticket_guard_qa.test_suites.exception_cases import find_covering_suites, load_exception_cases
from ticket_guard_qa.test_suites.suite_registry import list_suites

RECENT_RUN_COUNT = 10
MAX_SHOWN_ANSWER_KEY_ENTRIES = 100
ENDPOINT_TITLE_BY_NAME = {BROWSER_EVENTS_ENDPOINT: "브라우저 이벤트", ACTION_ENDPOINT: "예매 확정", "kafka": "토픽 주입"}

router = APIRouter()


@router.get("/cases", response_class=HTMLResponse)
def show_test_cases(request: Request, run_id: str | None = None) -> HTMLResponse:
    settings = request.app.state.settings
    suites = list_suites()
    exception_rows = [(case, find_covering_suites(case.related_code, suites)) for case in load_exception_cases(settings.case_data_dir)]

    run_repository = request.app.state.run_service.run_repository
    answer_key_repository = request.app.state.answer_key_repository
    run_ids_with_answer_key = [
        recent_run_id for recent_run_id in run_repository.list_recent_run_ids(RECENT_RUN_COUNT)
        if answer_key_repository.load(recent_run_id)
    ]
    selected_run_id = run_id or (run_ids_with_answer_key[0] if run_ids_with_answer_key else None)
    answer_key = answer_key_repository.load(selected_run_id) if selected_run_id else {}
    actor_counts = Counter(answer_key.values())
    return render_screen(request, "screen_c1_test_cases.html", {
        "active_tab": "qa",
        "active_subtab": "cases",
        "exception_rows": exception_rows,
        "covered_case_count": sum(bool(covering_suites) for _, covering_suites in exception_rows),
        "unsupported_case_count": sum(case.system_error_code is None for case, _ in exception_rows),
        "contract_cases": load_contract_cases(settings.case_data_dir),
        "endpoint_title_by_name": ENDPOINT_TITLE_BY_NAME,
        "run_ids": run_ids_with_answer_key,
        "selected_run_id": selected_run_id,
        "answer_key_total": len(answer_key),
        "actor_rows": [(get_bot_type_info(actor_type), actor_counts[actor_type]) for actor_type in list_actor_types() if actor_counts[actor_type]],
        "answer_key_entries": [(session_key, get_bot_type_info(actor_type))
                               for session_key, actor_type in list(answer_key.items())[:MAX_SHOWN_ANSWER_KEY_ENTRIES]],
    })
