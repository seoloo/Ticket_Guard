"""04 · 01 화면 표기 · 최종 판정 건수 · Suite 메시지 줄 나누기"""
from datetime import datetime, timezone

from ticket_guard_qa.dashboard.screen_format import format_verdict_detail, split_message_lines
from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome, TargetKind
from ticket_guard_qa.domain.models import CriterionResult, RunConfig, RunSummary, SuiteResult

STARTED_AT = datetime(2026, 11, 6, tzinfo=timezone.utc)


def build_summary(status: RunStatus, outcomes: list[SuiteOutcome], criteria: list[bool | None]) -> RunSummary:
    return RunSummary(
        run_id="run-test", run_config=RunConfig(TargetKind.LIVE, ("event_delivery",)), status=status, started_at=STARTED_AT,
        suite_results=[SuiteResult(f"suite_{index}", outcome) for index, outcome in enumerate(outcomes)],
        criterion_results=[CriterionResult(f"criterion_{index}", None, is_passed) for index, is_passed in enumerate(criteria)],
    )


def test_failed_run_counts_failed_criteria_and_suites():
    summary = build_summary(RunStatus.FAILED, [SuiteOutcome.FAILED], [None] * 7)
    assert format_verdict_detail(summary) == "기준 0 · Suite 1"


def test_passed_run_shows_na_when_no_criteria_measured():
    assert format_verdict_detail(build_summary(RunStatus.PASSED, [SuiteOutcome.PASSED], [None] * 7)) == "기준 N/A · Suite 1/1"
    measured = build_summary(RunStatus.PASSED, [SuiteOutcome.PASSED, SuiteOutcome.SKIPPED], [True, True, None])
    assert format_verdict_detail(measured) == "기준 2/2 · Suite 1/2"


def test_message_lines_split_by_kind():
    message = "FAIL: 서버 이벤트 누락 1건\n좌석 클릭 이벤트 950/952\n참고: 트래픽 오류 VU 3명\n"
    assert split_message_lines(message) == [
        ("fail", "서버 이벤트 누락 1건"), ("info", "좌석 클릭 이벤트 950/952"), ("ref", "트래픽 오류 VU 3명"),
    ]
    assert split_message_lines("") == []
    assert split_message_lines("예매 완료 20 · 매진 0") == [("info", "예매 완료 20 · 매진 0")]
