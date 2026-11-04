"""사람 · 봇 행동 값 계산 · Locust · Playwright가 공용으로 사용 · 정답표 저장 금지 · 식은 macro_bots/behavior_sampling.py 한 곳"""
import random

from ticket_guard_qa.macro_bots.behavior_sampling import pick_click_interval_ms, pick_entry_delay_ms
from ticket_guard_qa.macro_bots.bot_profiles import BotProfile


def pick_click_interval_sec(profile: BotProfile, random_source: random.Random) -> float:
    return pick_click_interval_ms(profile.behavior, random_source) / 1000


def pick_entry_delay_sec(profile: BotProfile, random_source: random.Random) -> float:
    return pick_entry_delay_ms(profile.behavior, random_source) / 1000
