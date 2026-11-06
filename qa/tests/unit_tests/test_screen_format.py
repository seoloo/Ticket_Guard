"""04 · 01 화면 표기 · 최종 판정 근거 · Suite 메시지 줄 나누기 · 합격 기준 상태 4종"""
from datetime import datetime, timezone

from ticket_guard_qa.dashboard.criterion_status import (
    CriterionStatus,
    build_criterion_rows,
    count_statuses,
    format_target,
)
from ticket_guard_qa.dashboard.screen_format import split_message_lines
from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import CriterionResult, RunConfig, RunSummary, SuiteResult
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA, PASS_CRITERION_BY_ID

STARTED_AT = datetime(2026, 11, 6, tzinfo=timezone.utc)
SUITE_TITLES = {"verdict_accuracy": "판정 정확도", "pipeline_latency": "Gold 반영 지연", "failure_recovery": "장애 복구"}


def build_summary(status: RunStatus, outcomes: list[SuiteOutcome], criteria: list[bool | None]) -> RunSummary:
    return RunSummary(
        run_id="run-test", run_config=RunConfig(TargetKind.LIVE, ("event_delivery",)), status=status, started_at=STARTED_AT,
        suite_results=[SuiteResult(f"suite_{index}", outcome) for index, outcome in enumerate(outcomes)],
        criterion_results=[CriterionResult(f"criterion_{index}", None, is_passed) for index, is_passed in enumerate(criteria)],
    )


def test_summary_counts_suites_and_measured_criteria():
    failed = build_summary(RunStatus.FAILED, [SuiteOutcome.FAILED], [None] * 7)
    assert (failed.failed_suite_count, failed.failed_criteria_count, failed.measured_criteria_count) == (1, 0, 0)
    measured = build_summary(RunStatus.PASSED, [SuiteOutcome.PASSED, SuiteOutcome.SKIPPED], [True, True, None])
    assert (measured.passed_suite_count, measured.measured_criteria_count) == (1, 2)


def test_message_lines_split_by_kind():
    message = "FAIL: 서버 이벤트 누락 1건\n좌석 클릭 이벤트 950/952\n참고: 트래픽 오류 VU 3명\n"
    assert split_message_lines(message) == [
        ("fail", "서버 이벤트 누락 1건"), ("info", "좌석 클릭 이벤트 950/952"), ("ref", "트래픽 오류 VU 3명"),
    ]
    assert split_message_lines("") == []
    assert split_message_lines("예매 완료 20 · 매진 0") == [("info", "예매 완료 20 · 매진 0")]


def test_every_criterion_has_plain_name_meaning_and_suite():
    for criterion in PASS_CRITERIA:
        assert criterion.display_name and criterion.meaning and criterion.measuring_suite_name, criterion.criterion_id


def test_target_words():
    assert format_target(PASS_CRITERION_BY_ID["api_latency"]) == "3초 이하"
    assert format_target(PASS_CRITERION_BY_ID["api_error_rate"]) == "0%"
    assert format_target(PASS_CRITERION_BY_ID["bot_abd_detection"]) == "90% 이상"


def test_criterion_statuses_pass_fail_not_targeted_and_not_measurable():
    results = {criterion.criterion_id: CriterionResult(criterion.criterion_id, None, None) for criterion in PASS_CRITERIA}
    results["gold_latency"] = CriterionResult("gold_latency", 6.8, True)
    results["bot_c_detection"] = CriterionResult("bot_c_detection", 50.0, False)
    summary = RunSummary(
        run_id="run-test", run_config=RunConfig(TargetKind.LIVE, ("verdict_accuracy", "pipeline_latency")),
        status=RunStatus.FAILED, started_at=STARTED_AT,
        suite_results=[
            SuiteResult("verdict_accuracy", SuiteOutcome.SKIPPED, message="시스템 판정 없음 · AGENTS.md 5장"),
            SuiteResult("pipeline_latency", SuiteOutcome.PASSED, metrics={"gold_latency_p95_sec": 6.8}),
        ],
        criterion_results=list(results.values()),
    )
    rows = {row.criterion.criterion_id: row for row in build_criterion_rows(summary, SUITE_TITLES)}
    assert (rows["gold_latency"].status, rows["gold_latency"].detail) == (CriterionStatus.PASSED, "측정 Suite · Gold 반영 지연")
    assert (rows["bot_c_detection"].status, rows["bot_c_detection"].detail) == (CriterionStatus.FAILED, "목표 70% 이상 미달")
    assert (rows["recovery_time"].status, rows["recovery_time"].detail) == (CriterionStatus.NOT_TARGETED, "장애 복구 미선택")
    assert (rows["api_latency"].status, rows["api_latency"].detail) == (CriterionStatus.NOT_MEASURABLE, "시스템 판정 없음")
    assert count_statuses(list(rows.values())) == {
        CriterionStatus.PASSED: 1, CriterionStatus.FAILED: 1, CriterionStatus.NOT_TARGETED: 1, CriterionStatus.NOT_MEASURABLE: 4,
    }
