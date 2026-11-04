"""db 스키마 대응 · 계약 사례 형식 · Mock이 SESSION_VERDICTS · SESSION_FEATURES 모양을 내는지 · docs/contracts.md 3 · 5장"""
from dataclasses import fields

from ticket_guard_qa.domain.enums import ActorType, VerdictStage
from ticket_guard_qa.domain.models import (
    FEATURE_FIELD_BY_BEHAVIOR_FIELD,
    SessionBehavior,
    SessionFeatureRecord,
    SessionVerdictRecord,
    verdicts_from_records,
)
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE
from ticket_guard_qa.scoring.detection_breakdown import count_rule_hits
from ticket_guard_qa.settings import QA_ROOT_DIR
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.test_suites.event_contract import KAFKA_ENDPOINT, QUARANTINE_REASON_CODES, load_contract_cases

CASE_DATA_DIR = QA_ROOT_DIR / "case_data"


def test_every_contract_case_has_storage_expectation():
    cases = load_contract_cases(CASE_DATA_DIR)
    assert cases
    for case in cases:
        assert case.expected_storage is not None, case.case_name
        assert set(case.expected_storage.quarantine_reason_codes) <= set(QUARANTINE_REASON_CODES), case.case_name


def test_kafka_cases_carry_messages_not_http_requests():
    kafka_cases = [case for case in load_contract_cases(CASE_DATA_DIR) if case.endpoint == KAFKA_ENDPOINT]
    assert kafka_cases
    for case in kafka_cases:
        assert case.kafka_messages and not case.requests, case.case_name
        assert all({"key", "value"} <= set(message) for message in case.kafka_messages), case.case_name


def test_mock_returns_schema_shaped_records():
    system_target = build_fake_system_target(7)
    bot_session = system_target.booking_api.start_virtual_user_session(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A])
    system_target.booking_api.start_virtual_user_session(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN])

    verdict_records = system_target.verdict_reader.read_verdict_records("run-test")
    features = system_target.pipeline_reader.read_session_features("run-test")
    assert [record.booking_attempt_id for record in verdict_records] == [record.booking_attempt_id for record in features]
    assert verdicts_from_records(verdict_records) == system_target.verdict_reader.read_session_verdicts("run-test")

    bot_verdict = next(record for record in verdict_records if record.booking_attempt_id == bot_session.session_key)
    assert "MOCK-R2" in bot_verdict.matched_rules  # 고속 간격
    bot_feature = next(record for record in features if record.booking_attempt_id == bot_session.session_key)
    assert bot_feature.click_interval_mean_ms < 200  # 봇 A 평균 간격 근처
    assert bot_feature.computed_at > bot_feature.window_end  # Gold 반영은 구간 뒤
    assert len(system_target.pipeline_reader.read_gold_latency_sec("run-test")) == 2


def test_rule_hits_count_only_detected_sessions():
    def record(stage, rules):
        return SessionVerdictRecord("attempt", stage, 0.5, rules, "mock-1", None)

    hits = count_rule_hits([
        record(VerdictStage.HOLD, ("R2", "R1")),
        record(VerdictStage.CHALLENGE, ("R1",)),
        record(VerdictStage.OBSERVE, ("R3",)),  # 탐지 아님 · 세지 않음
    ])
    assert hits == {"R1": 2, "R2": 1}


def test_every_bot_parameter_maps_to_feature_field():
    """새 봇 파라미터를 추가하면 SESSION_FEATURES 대응도 정해야 함"""
    feature_names = {field.name for field in fields(SessionFeatureRecord)}
    assert set(FEATURE_FIELD_BY_BEHAVIOR_FIELD) == {field.name for field in fields(SessionBehavior)}
    assert {name for name in FEATURE_FIELD_BY_BEHAVIOR_FIELD.values() if name} <= feature_names
