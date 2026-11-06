from dataclasses import fields, replace
from datetime import datetime, timezone

import pytest

from ticket_guard_qa.domain.detection_targets import DETECTION_TARGETS, find_detection_target
from ticket_guard_qa.domain.enums import ActorType, VerdictStage
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.macro_bots.behavior_fields import BEHAVIOR_FIELD_SPECS, BehaviorInputError, behavior_to_dict, parse_behavior_form
from ticket_guard_qa.macro_bots.bot_catalog import BOT_TYPE_CATALOG, find_bot_type_by_slug
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileLockedError, BotProfileStore
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE
from ticket_guard_qa.macro_bots.bot_trial_run import run_trial_sessions
from ticket_guard_qa.scoring.detection_breakdown import VerdictOutcome, build_actor_detection_rows_from_details, classify_verdict
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target

SAVED_AT = datetime(2026, 11, 4, tzinfo=timezone.utc)


# 확장 지점 · 새 종류 · 새 행동 값을 추가할 때 빠뜨리면 여기서 실패
def test_every_actor_type_has_catalog_entry_and_default_behavior():
    assert {info.actor_type for info in BOT_TYPE_CATALOG} == set(ActorType)
    assert set(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE) == set(ActorType)


def test_every_behavior_field_has_input_spec():
    assert [spec.field_name for spec in BEHAVIOR_FIELD_SPECS] == [field.name for field in fields(SessionBehavior)]


def test_detection_targets_do_not_overlap():
    grouped_types = [actor_type for target in DETECTION_TARGETS for actor_type in target.actor_types]
    assert len(grouped_types) == len(set(grouped_types))
    assert find_detection_target(ActorType.BOT_NEW) is None  # 새 유형 = 목표 없음


def test_bot_slug_lookup():
    assert find_bot_type_by_slug("BOT_C").actor_type is ActorType.BOT_C
    assert find_bot_type_by_slug("bot_z") is None


def test_behavior_form_rejects_out_of_range_value():
    form = behavior_to_dict(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A]) | {"sessions_per_device": "0"}
    with pytest.raises(BehaviorInputError, match="디바이스당"):
        parse_behavior_form(form)


def test_saved_version_becomes_current_and_old_version_stays_readable(qa_database):
    store = BotProfileStore(qa_database)
    changed = replace(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_B], click_interval_deviation_ms=200)
    saved = store.save_new_version(ActorType.BOT_B, changed, " 흔들림 키움 ", SAVED_AT)

    assert saved.version_number == 2
    assert saved.change_note == "흔들림 키움"
    current = store.load_current_registry()
    assert current.get_profile(ActorType.BOT_B).behavior == changed
    assert current.get_profile(ActorType.BOT_A).version_number == 1  # 다른 종류는 그대로
    old = store.load_registry_for_versions({"BOT_B": 1})
    assert old.get_profile(ActorType.BOT_B).behavior == DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_B]
    assert [profile.version_number for profile in store.list_version_history(ActorType.BOT_B)] == [2, 1]


def test_locked_bot_cannot_be_saved(qa_database):
    with pytest.raises(BotProfileLockedError):
        BotProfileStore(qa_database).save_new_version(
            ActorType.BOT_NEW, DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_NEW], "", SAVED_AT
        )


def test_trial_run_is_repeatable_and_separates_bot_from_human():
    bot_result = run_trial_sessions(build_fake_system_target(1), DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A])
    again = run_trial_sessions(build_fake_system_target(1), DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A])
    human_result = run_trial_sessions(build_fake_system_target(1), DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN])
    assert bot_result == again  # 같은 값 = 같은 결과
    assert bot_result.detection_rate_percent > human_result.detection_rate_percent


def test_detection_rows_from_saved_details():
    details = {"confusion_matrix": {
        "BOT_C": {"NORMAL": 3, "CHALLENGE": 7},
        "HUMAN": {"NORMAL": 99, "HOLD": 1},
    }}
    rows = build_actor_detection_rows_from_details(details)
    assert rows[ActorType.BOT_C].detection_rate_percent == 70.0
    assert rows[ActorType.BOT_C].is_meeting_target is True  # ≥ 70%
    assert rows[ActorType.HUMAN].is_meeting_target is True  # 오탐 1% ≤ 1%
    assert rows[ActorType.BOT_A].detection_rate_percent is None  # 세션 없음


def test_verdict_outcome_colors():
    assert classify_verdict(ActorType.BOT_A, VerdictStage.OBSERVE) is VerdictOutcome.MISSED
    assert classify_verdict(ActorType.BOT_A, VerdictStage.CHALLENGE) is VerdictOutcome.CAUGHT
    assert classify_verdict(ActorType.HUMAN, VerdictStage.HOLD) is VerdictOutcome.FALSE_POSITIVE
    assert classify_verdict(ActorType.HUMAN, VerdictStage.OBSERVE) is VerdictOutcome.CORRECT_PASS
