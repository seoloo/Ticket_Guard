"""화면 숫자 · 시간 표기 · 단위는 지표 이름 끝(_sec · _percent)으로 판단"""
from datetime import datetime, timezone

from jinja2 import Environment

from ticket_guard_qa.domain.enums import ActorType, RunStatus
from ticket_guard_qa.domain.models import FAIL_LINE_PREFIX, MESSAGE_LINE_SEPARATOR, REFERENCE_LINE_PREFIX, RunSummary
from ticket_guard_qa.macro_bots.bot_catalog import BotTypeInfo, get_bot_type_info

SECONDS_PER_MINUTE = 60


def format_metric(value: float | None, metric_name: str) -> str:
    if value is None:
        return "-"
    if metric_name.endswith("_sec"):
        return f"{value:.2f}초"
    if metric_name.endswith("_percent"):
        return f"{value:.1f}%"
    return f"{value:,.0f}"


def format_threshold(comparison: str, threshold: float, metric_name: str) -> str:
    symbol = "≤" if comparison == "<=" else "≥"
    unit = "초" if metric_name.endswith("_sec") else "%" if metric_name.endswith("_percent") else ""
    return f"{symbol} {threshold:g}{unit}"


def format_rough_duration(seconds: float) -> str:
    if seconds < SECONDS_PER_MINUTE:
        return f"약 {max(round(seconds), 1)}초"
    return f"약 {round(seconds / SECONDS_PER_MINUTE)}분"


def format_time_ago(moment: datetime | None) -> str:
    if moment is None:
        return "-"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)  # SQLite는 시간대를 버림
    elapsed_sec = (datetime.now(timezone.utc) - moment).total_seconds()
    if elapsed_sec < SECONDS_PER_MINUTE:
        return "방금 전"
    if elapsed_sec < 3600:
        return f"{int(elapsed_sec // SECONDS_PER_MINUTE)}분 전"
    if elapsed_sec < 86400:
        return f"{int(elapsed_sec // 3600)}시간 전"
    return f"{int(elapsed_sec // 86400)}일 전"


def find_bot_type_info(actor_type: ActorType | str) -> BotTypeInfo:
    return get_bot_type_info(ActorType(actor_type))


def format_verdict_detail(summary: RunSummary) -> str:
    """최종 판정 옆 · FAIL = 실패 기준 수 · 실패 Suite 수 · PASS = 통과 기준 · 통과 Suite"""
    if summary.status is RunStatus.FAILED:
        return f"기준 {summary.failed_criteria_count} · Suite {summary.failed_suite_count}"
    measured = summary.measured_criteria_count
    criteria_text = f"{summary.passed_criteria_count}/{measured}" if measured else "N/A"
    return f"기준 {criteria_text} · Suite {summary.passed_suite_count}/{len(summary.suite_results)}"


def split_message_lines(message: str) -> list[tuple[str, str]]:
    """Suite 메시지 → (fail | ref | info, 문구) 목록 · 04 화면 · HTML 리포트"""
    lines = []
    for line in filter(None, (raw.strip() for raw in (message or "").split(MESSAGE_LINE_SEPARATOR))):
        if line.startswith(FAIL_LINE_PREFIX):
            lines.append(("fail", line.removeprefix(FAIL_LINE_PREFIX)))
        elif line.startswith(REFERENCE_LINE_PREFIX):
            lines.append(("ref", line.removeprefix(REFERENCE_LINE_PREFIX)))
        else:
            lines.append(("info", line))
    return lines


def register_screen_filters(environment: Environment) -> None:
    environment.filters["metric"] = format_metric
    environment.filters["threshold"] = format_threshold
    environment.filters["rough_duration"] = format_rough_duration
    environment.filters["time_ago"] = format_time_ago
    environment.filters["bot_type_info"] = find_bot_type_info
    environment.filters["verdict_detail"] = format_verdict_detail
    environment.filters["message_lines"] = split_message_lines
