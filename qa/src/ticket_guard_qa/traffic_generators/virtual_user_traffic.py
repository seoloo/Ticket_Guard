"""VU 동시 실행 · 예매 오픈 버스트 · 오픈 전 로그인 → 오픈(T0) + 진입 지연 → 예매 · 행동 값은 macro_bots"""
import asyncio
import random
import time
from collections.abc import Callable

from ticket_guard_qa.domain.models import SessionBehavior, SessionKey, VirtualUserSessionPlan, VirtualUserSessionResult
from ticket_guard_qa.macro_bots.behavior_sampling import pick_click_interval_ms, pick_entry_delay_ms
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError, BookingApi

ALL_SEAT_IDS = tuple(f"{row}{number}" for row in "ABCDEFGHIJ" for number in range(1, 11))  # 시스템 지정석 A1 ~ J10
CLICK_INTERVAL_COUNT = 3  # 좌석 2석 클릭 + 확정 버튼
PRE_OPEN_LOGIN_SEC = 3.0  # 오픈 전 로그인 시간 · 사람도 미리 로그인
PROGRESS_REPORT_EVERY = 10
TIMEOUT_FAILED_STEP = "time_limit · TIMEOUT"  # Run 설정 시험 시간 초과

ProgressCallback = Callable[[list[VirtualUserSessionResult | None]], None]  # 계획 순서 · 아직 안 끝난 VU = None


def build_session_plans(behaviors: list[SessionBehavior], random_seed: int) -> list[VirtualUserSessionPlan]:
    """행동 값 → 실제 대기 시간 · 고를 좌석 순서 · 같은 시드 = 같은 계획"""
    random_source = random.Random(f"traffic-{random_seed}")  # 정답표 시드와 분리
    plans = []
    for behavior in behaviors:
        preferred_seat_ids = list(ALL_SEAT_IDS)
        random_source.shuffle(preferred_seat_ids)
        plans.append(VirtualUserSessionPlan(
            behavior=behavior,
            entry_delay_ms=pick_entry_delay_ms(behavior, random_source),
            click_intervals_ms=tuple(pick_click_interval_ms(behavior, random_source) for _ in range(CLICK_INTERVAL_COUNT)),
            preferred_seat_ids=tuple(preferred_seat_ids),
        ))
    return plans


def reset_before_traffic(booking_api: BookingApi) -> str:
    """판매 좌석 · 진행 중 예매 비우기 · Run마다 같은 조건"""
    if booking_api.reset_test_data():
        return "시험 데이터 초기화"
    return "초기화 건너뜀 · 관리자 계정 미설정"


def send_virtual_user_traffic(
    booking_api: BookingApi,
    session_plans: list[VirtualUserSessionPlan],
    time_limit_sec: float,
    on_progress: ProgressCallback | None = None,
) -> list[VirtualUserSessionResult]:
    """VU 전원 동시 실행 · 결과는 계획 순서 · 시험 시간 넘으면 남은 VU는 TIMEOUT"""
    capacity = booking_api.virtual_user_capacity()
    if capacity is not None and len(session_plans) > capacity:
        raise AccountPoolExhaustedError(
            f"시험 계정 부족 · VU {len(session_plans)}명 · 계정 {capacity}개 · 저장소 .env QA_TEST_ACCOUNT_COUNT 확인"
        )
    return asyncio.run(run_concurrent_sessions(booking_api, session_plans, time_limit_sec, on_progress))


async def run_concurrent_sessions(
    booking_api: BookingApi,
    session_plans: list[VirtualUserSessionPlan],
    time_limit_sec: float,
    on_progress: ProgressCallback | None,
) -> list[VirtualUserSessionResult]:
    open_at_monotonic = time.monotonic() + PRE_OPEN_LOGIN_SEC
    deadline = time.monotonic() + time_limit_sec
    results: list[VirtualUserSessionResult | None] = [None] * len(session_plans)
    index_by_task = {
        asyncio.create_task(booking_api.run_virtual_user_session(plan, open_at_monotonic)): index
        for index, plan in enumerate(session_plans)
    }
    pending = set(index_by_task)
    reported_count = 0
    while pending:
        done, pending = await asyncio.wait(
            pending, timeout=max(deadline - time.monotonic(), 0.0), return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            break  # 시험 시간 초과
        for task in done:
            results[index_by_task[task]] = read_task_result(task, index_by_task[task])
        finished_count = len(session_plans) - len(pending)
        if on_progress and (finished_count - reported_count >= PROGRESS_REPORT_EVERY or not pending):
            on_progress(results)
            reported_count = finished_count

    for task in pending:
        task.cancel()  # 취소돼도 VU마다 예매 취소 정리는 실행
    await asyncio.gather(*pending, return_exceptions=True)
    return [
        result or VirtualUserSessionResult(SessionKey(f"timeout-{index + 1:04d}"), 0.0, is_error=True,
                                           failed_step=TIMEOUT_FAILED_STEP)
        for index, result in enumerate(results)
    ]


def read_task_result(task: asyncio.Task, index: int) -> VirtualUserSessionResult:
    try:
        return task.result()
    except Exception as error:  # noqa: BLE001 · VU 하나 실패가 전체를 멈추지 않게
        return VirtualUserSessionResult(SessionKey(f"failed-{index + 1:04d}"), 0.0, is_error=True,
                                        failed_step=f"qa · {type(error).__name__}")
