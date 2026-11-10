"""접속 방식 · 나눠서 진입 · 회차 나누기 · 회차 차례 실행 · 같은 기기 창은 같은 회차 · 입력 확인 · 예상 시간"""
import asyncio
import time
from dataclasses import replace

import pytest

from ticket_guard_qa.domain.enums import ActorType, TargetKind
from ticket_guard_qa.domain.models import RunConfig, SessionKey, VirtualUserSessionResult
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE, BotProfileRegistry
from ticket_guard_qa.test_runs.run_estimate import calculate_traffic_suite_sec
from ticket_guard_qa.traffic_generators.virtual_user_traffic import (
    build_session_plans,
    send_virtual_user_traffic,
    split_into_waves,
)

HUMAN_BEHAVIOR = DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN]
BOT_D_BEHAVIOR = replace(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_D], sessions_per_device=3)


def test_split_into_waves_keeps_remainder_in_last_wave():
    assert [len(wave) for wave in split_into_waves(200, 40)] == [40] * 5
    assert [len(wave) for wave in split_into_waves(200, 45)] == [45, 45, 45, 45, 20]
    assert split_into_waves(200, 0) == [range(200)]  # 한 번에 전원 진입


def test_entry_title_reads_like_the_screen():
    assert RunConfig(TargetKind.LIVE, (), virtual_user_count=200, wave_size=40).entry_title == "40명씩 5회"
    assert RunConfig(TargetKind.LIVE, (), virtual_user_count=200, wave_size=45).entry_title == "45명씩 4회 + 마지막 20명"
    assert RunConfig(TargetKind.LIVE, (), virtual_user_count=200).entry_title == "한 번에 전원 진입"


class RecordingBookingApi:
    """VU마다 시작 · 종료 시각 · 오픈 시각 기록 · 실제 대상 없이"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float, float, float]] = []  # (기기, 오픈 시각, 시작, 종료)

    def virtual_user_capacity(self):
        return None

    async def run_virtual_user_session(self, session_plan, open_at_monotonic):
        started_at = time.monotonic()
        await asyncio.sleep(0.02)
        self.calls.append((session_plan.device_key, open_at_monotonic, started_at, time.monotonic()))
        return VirtualUserSessionResult(SessionKey(f"attempt-{len(self.calls)}"), 1.0, is_error=False)


def test_next_wave_starts_after_previous_wave_finishes():
    api = RecordingBookingApi()
    plans = build_session_plans([HUMAN_BEHAVIOR] * 5, random_seed=1)
    results = send_virtual_user_traffic(api, plans, 10, wave_size=2)

    assert len(results) == 5 and not any(result.is_error for result in results)
    open_times = {open_at for _, open_at, _, _ in api.calls}
    assert len(open_times) == 3  # 2명 · 2명 · 1명 = 회차마다 새 오픈 시각
    calls_by_open = sorted(([call for call in api.calls if call[1] == open_at] for open_at in open_times),
                           key=lambda wave: min(start for _, _, start, _ in wave))  # 시작 순서 · 오픈 시각은 화면 조회 시간마다 다름
    assert [len(wave) for wave in calls_by_open] == [2, 2, 1]
    for previous_wave, next_wave in zip(calls_by_open, calls_by_open[1:]):
        assert max(end for *_, end in previous_wave) <= min(start for _, _, start, _ in next_wave)


def test_same_device_windows_stay_in_one_wave():
    plans = build_session_plans([BOT_D_BEHAVIOR] * 6, random_seed=1, wave_size=4)
    device_keys = [plan.device_key for plan in plans]

    assert device_keys[:3] == [device_keys[0]] * 3 and device_keys[3] != device_keys[0]  # 1회차 = 기기 2대(3창 + 1창)
    assert set(device_keys[:4]).isdisjoint(device_keys[4:])  # 2회차 기기는 새 번호
    assert len(set(device_keys)) == 3


def test_estimate_adds_each_wave():
    registry = BotProfileRegistry()
    burst = calculate_traffic_suite_sec(RunConfig(TargetKind.LIVE, (), virtual_user_count=200), registry, 25)
    waves = calculate_traffic_suite_sec(RunConfig(TargetKind.LIVE, (), virtual_user_count=200, wave_size=40), registry, 25)
    assert waves > burst  # 회차마다 오픈 전 준비 · 대기열 대기


def test_setup_form_checks_wave_size(qa_settings):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ticket_guard_qa.dashboard.dashboard_app import create_dashboard_app
    from ticket_guard_qa.dashboard.dependencies import ADMIN_USER_HEADER

    client = TestClient(create_dashboard_app(qa_settings), headers={ADMIN_USER_HEADER: "qa-admin"})
    form = {"target_kind": "live", "suite_names": ["booking_flow"], "virtual_user_count": "200", "duration_sec": "0",
            "percent_HUMAN": "100", "entry_mode": "wave"}
    assert client.post("/runs/estimate", data={**form, "wave_size": "250"}).status_code == 400  # VU보다 큼
    assert client.post("/runs/estimate", data={**form, "wave_size": "40"}).status_code == 200
    page = client.post("/runs", data={**form, "wave_size": "0"}).text
    assert "회차당 인원 1 ~ 200명 사이 입력 필요" in page
