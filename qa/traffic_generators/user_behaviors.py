"""사람 · 봇 행동 값 계산 · Locust · Playwright가 공용으로 사용 · 정답표 저장 금지"""
import random

from ticket_guard_qa.macro_bots.bot_profiles import BotProfile


def pick_click_interval_sec(profile: BotProfile, random_source: random.Random) -> float:
    interval_ms = random_source.gauss(profile.click_interval_mean_ms, profile.click_interval_deviation_ms)
    return max(interval_ms, 0.0) / 1000  # 음수 간격 금지


def pick_entry_delay_sec(profile: BotProfile, random_source: random.Random) -> float:
    jitter_ms = random_source.uniform(0, profile.click_interval_deviation_ms)
    return (profile.entry_delay_after_open_ms + jitter_ms) / 1000
