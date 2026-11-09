from dataclasses import fields, replace
from datetime import datetime, timezone

import pytest

from ticket_guard_qa.domain.detection_targets import DETECTION_TARGETS, find_detection_target
from ticket_guard_qa.domain.enums import ActorType, VerdictStage
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.domain.rule_sets import MOCK_RULE_SET_VERSION
from ticket_guard_qa.macro_bots.browser_capture import (
    CAPTURE_STEPS,
    CaptureFrame,
    build_mock_capture_frames,
    load_capture_frames,
    save_capture_frames,
)
from ticket_guard_qa.macro_bots.behavior_fields import BEHAVIOR_FIELD_SPECS, BehaviorInputError, behavior_to_dict, parse_behavior_form
from ticket_guard_qa.macro_bots.behavior_description import describe_behavior
from ticket_guard_qa.macro_bots.bot_catalog import BOT_ROLE_CATALOG, BOT_TYPE_CATALOG, find_bot_type_by_slug
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileLockedError, BotProfileStore
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE
from ticket_guard_qa.macro_bots.bot_trial_run import run_trial_sessions
from ticket_guard_qa.macro_bots.rule_hit_preview import RULE_PENDING_REASON, predict_rule_hits
from ticket_guard_qa.scoring.detection_breakdown import VerdictOutcome, build_actor_detection_rows_from_details, classify_verdict
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target, find_matched_mock_rules

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


def test_every_bot_type_belongs_to_listed_role_and_has_signals():
    listed_roles = {role_info.role for role_info in BOT_ROLE_CATALOG}
    for info in BOT_TYPE_CATALOG:
        assert info.role in listed_roles  # B1 구획에 빠짐없이 표시
        assert info.detection_signals and info.purpose


def test_behavior_description_reads_values_in_plain_words():
    bot_a_lines = describe_behavior(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A])
    assert [line.step_title for line in bot_a_lines] == [
        "예매 전 화면 조회", "예매 시작 시점", "좌석 클릭 간격", "매진 좌석 대응", "동시 예매 창", "브라우저 흔적"]
    by_step = {line.step_title: line for line in bot_a_lines}
    assert by_step["예매 전 화면 조회"].headline == "공연 목록 · 상세 화면 조회 없이 바로 예매"
    assert by_step["예매 시작 시점"].headline == "예매 오픈과 동시에 예매하기 버튼 클릭"
    assert "기계적" in by_step["좌석 클릭 간격"].detail and "0.08초" in by_step["좌석 클릭 간격"].headline
    assert by_step["매진 좌석 대응"].detail == "대기 없이 즉시 재시도"
    human = {line.step_title: line for line in describe_behavior(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN])}
    assert human["예매 시작 시점"].headline == "예매 오픈 3초 뒤 예매하기 버튼 클릭"
    assert human["예매 전 화면 조회"].headline == "예매 오픈 전 공연 목록 · 상세 화면 3회 조회"
    assert "사람처럼 불규칙" in human["좌석 클릭 간격"].detail
    bot_d = {line.step_title: line for line in describe_behavior(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_D])}
    assert "예매 창 8개" in bot_d["동시 예매 창"].headline


def test_browser_trace_choice_rejects_unknown_value():
    form = behavior_to_dict(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A]) | {"browser_trace_level": "2"}
    with pytest.raises(BehaviorInputError, match="범위 오류"):
        parse_behavior_form(form)


def test_bot_slug_lookup():
    assert find_bot_type_by_slug("BOT_C").actor_type is ActorType.BOT_C
    assert find_bot_type_by_slug("bot_z") is None


def test_behavior_form_rejects_out_of_range_value():
    form = behavior_to_dict(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A]) | {"sessions_per_device": "0"}
    with pytest.raises(BehaviorInputError, match="동시 예매 창"):
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


def test_rule_preview_matches_mock_verdict_rules():
    for behavior in DEFAULT_BEHAVIOR_BY_ACTOR_TYPE.values():
        previews = predict_rule_hits(behavior, MOCK_RULE_SET_VERSION)
        assert all(preview.is_expected_hit is not None for preview in previews)
        assert tuple(preview.rule_id for preview in previews if preview.is_expected_hit) == find_matched_mock_rules(behavior)


def test_rule_preview_pending_for_unknown_rule_set():
    previews = predict_rule_hits(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A], "live-v1")
    assert [preview.rule_id for preview in previews] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert {preview.reason for preview in previews} == {RULE_PENDING_REASON}
    assert all(preview.is_expected_hit is None for preview in previews)


def test_mock_capture_frames_follow_booking_steps_and_seed():
    behavior = DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_C]
    frames = build_mock_capture_frames(behavior, 7)
    assert [frame.step for frame in frames] == list(CAPTURE_STEPS)
    assert frames[0].elapsed_ms == behavior.entry_delay_after_open_ms
    assert [frame.elapsed_ms for frame in frames] == sorted(frame.elapsed_ms for frame in frames)
    assert frames == build_mock_capture_frames(behavior, 7)


def test_saved_capture_frames_load_back(tmp_path):
    frames = [CaptureFrame("대기열", 120.0, 10, 20, "frame-1.png")]
    save_capture_frames(tmp_path, "run-1", frames)
    assert load_capture_frames(tmp_path, "run-1") == frames
    assert load_capture_frames(tmp_path, "run-unknown") == []
