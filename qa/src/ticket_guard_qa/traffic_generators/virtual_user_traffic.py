"""VU 동시 실행 · 예매 오픈 버스트 · 오픈 전 로그인 → 오픈(T0) + 진입 지연 → 예매 · 행동 값은 macro_bots"""
import asyncio
import random
import time
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass, replace

from ticket_guard_qa.domain.models import (
    PlannedUser,
    SessionBehavior,
    SessionKey,
    VirtualUserSessionPlan,
    VirtualUserSessionResult,
)
from ticket_guard_qa.macro_bots.bot_catalog import BROWSER_TRAFFIC, get_bot_type_info, list_bot_types
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry
from ticket_guard_qa.macro_bots.browser_capture import save_browser_capture_frames
from ticket_guard_qa.macro_bots.behavior_sampling import pick_click_interval_ms, pick_entry_delay_ms, pick_page_dwell_ms
from ticket_guard_qa.system_targets.target_interfaces import AccountPoolExhaustedError, BookingApi

ALL_SEAT_IDS = tuple(f"{row}{number}" for row in "ABCDEFGHIJ" for number in range(1, 11))  # 시스템 지정석 A1 ~ J10
CLICK_INTERVAL_COUNT = 3  # 좌석 2석 클릭 + 확정 버튼
PRE_OPEN_LOGIN_SEC = 3.0  # 오픈 전 로그인 시간 · 사람도 미리 로그인
PROGRESS_REPORT_EVERY = 10
TIMEOUT_FAILED_STEP = "time_limit · TIMEOUT"  # Run 설정 시험 시간 초과
DEVICE_KEY_PREFIX = "device-"

ProgressCallback = Callable[[list[VirtualUserSessionResult | None]], None]  # 계획 순서 · 아직 안 끝난 VU = None


def build_session_plans(
    behaviors: list[SessionBehavior], random_seed: int, browser_flags: list[bool] | None = None
) -> list[VirtualUserSessionPlan]:
    """행동 값 → 실제 대기 시간 · 고를 좌석 순서 · 같은 시드 = 같은 계획 · browser_flags = 브라우저 트래픽 유형"""
    random_source = random.Random(f"traffic-{random_seed}")  # 정답표 시드와 분리
    flags = browser_flags or [False] * len(behaviors)
    plans = []
    for behavior, uses_browser in zip(behaviors, flags):
        preferred_seat_ids = list(ALL_SEAT_IDS)
        random_source.shuffle(preferred_seat_ids)
        plans.append(VirtualUserSessionPlan(
            behavior=behavior,
            entry_delay_ms=pick_entry_delay_ms(behavior, random_source),
            click_intervals_ms=tuple(pick_click_interval_ms(behavior, random_source) for _ in range(CLICK_INTERVAL_COUNT)),
            preferred_seat_ids=tuple(preferred_seat_ids),
            page_dwell_ms=tuple(pick_page_dwell_ms(behavior, random_source) for _ in range(behavior.browse_page_count)),
            uses_browser=uses_browser,
        ))
    return assign_devices(plans)


def build_planned_user_session_plans(
    planned_users: list[PlannedUser], registry: BotProfileRegistry, random_seed: int
) -> list[VirtualUserSessionPlan]:
    """정답표 계획 순서 그대로 · 행동 값 = 실행 당시 봇 버전 · 브라우저 트래픽 유형은 화면으로 실행"""
    behaviors = [registry.get_profile(user.actor_type).behavior for user in planned_users]
    browser_flags = [get_bot_type_info(user.actor_type).traffic_channel == BROWSER_TRAFFIC for user in planned_users]
    return build_session_plans(behaviors, random_seed, browser_flags)


def save_browser_captures(report_output_dir: Path | None, run_id: str, planned_users: list[PlannedUser],
                          results: list[VirtualUserSessionResult]) -> int:
    """B3 화면 캡처 · B3 제목과 같은 유형(목록 순서상 첫 브라우저 트래픽 유형)의 첫 세션 · 저장한 프레임 수"""
    planned_types = {user.actor_type for user in planned_users}
    captured_type = next((info.actor_type for info in list_bot_types()
                          if info.traffic_channel == BROWSER_TRAFFIC and info.actor_type in planned_types), None)
    first_captured = next((result for user, result in zip(planned_users, results)
                           if user.actor_type == captured_type and result.capture_frames), None)
    if report_output_dir is None or first_captured is None:
        return 0
    save_browser_capture_frames(report_output_dir, run_id, list(first_captured.capture_frames))
    return len(first_captured.capture_frames)


@dataclass
class OpenDevice:
    device_key: str
    entry_delay_ms: float
    window_count: int


def assign_devices(plans: list[VirtualUserSessionPlan]) -> list[VirtualUserSessionPlan]:
    """기기 묶기 · 기기 1대당 예매 창 수만큼 같은 행동 값 VU를 한 기기로 · 같은 기기 창은 같은 순간 예매 시작"""
    open_device_by_behavior: dict[SessionBehavior, OpenDevice] = {}
    assigned: list[VirtualUserSessionPlan] = []
    device_count = 0
    for plan in plans:
        window_limit = plan.behavior.sessions_per_device
        open_device = open_device_by_behavior.get(plan.behavior)
        if window_limit > 1 and open_device and open_device.window_count < window_limit:
            open_device.window_count += 1
            assigned.append(replace(plan, device_key=open_device.device_key, entry_delay_ms=open_device.entry_delay_ms))
            continue
        device_count += 1
        device_key = f"{DEVICE_KEY_PREFIX}{device_count:04d}"
        if window_limit > 1:
            open_device_by_behavior[plan.behavior] = OpenDevice(device_key, plan.entry_delay_ms, 1)
        assigned.append(replace(plan, device_key=device_key))
    return assigned


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


def calculate_pre_open_sec(session_plans: list[VirtualUserSessionPlan]) -> float:
    """오픈 전 준비 시간 · 로그인 + 가장 긴 화면 조회 · 화면 조회는 오픈 전에 끝냄"""
    longest_browse_ms = max((sum(plan.page_dwell_ms) for plan in session_plans), default=0.0)
    return PRE_OPEN_LOGIN_SEC + longest_browse_ms / 1000


async def run_concurrent_sessions(
    booking_api: BookingApi,
    session_plans: list[VirtualUserSessionPlan],
    time_limit_sec: float,
    on_progress: ProgressCallback | None,
) -> list[VirtualUserSessionResult]:
    pre_open_sec = calculate_pre_open_sec(session_plans)
    open_at_monotonic = time.monotonic() + pre_open_sec
    deadline = time.monotonic() + time_limit_sec + (pre_open_sec - PRE_OPEN_LOGIN_SEC)  # 화면 조회 시간만큼 연장
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
