"""04 Suite 자체 검증 · 한 줄 결론 → 핵심 수치 타일 → 나머지 상세 · 원문 접기 (시안 05)
Suite 메시지 줄(FAIL · 참고 · 일반)에서 만듦 · 예매 흐름은 저장된 수치 사용 · 이전 Run 기록도 같은 화면"""
import re
from dataclasses import dataclass, field

from ticket_guard_qa.dashboard.screen_format import split_message_lines
from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import SuiteResult
from ticket_guard_qa.test_suites.booking_flow import BOOKING_FLOW_SUITE_NAME, STEP_TITLES

MAX_TILE_COUNT = 6
SEGMENT_SEPARATOR = " · "
LIST_SEPARATOR = ", "
ALERT_WORDS = ("오류", "누락", "중복", "실패", "위반", "초과", "차단 0")  # 0이 아니면 빨간 타일
FAILED_STEP_TITLES = {  # 세션 오류 코드 → 화면 문구 · 원문은 접기 안에 그대로
    "connection · ReadTimeout": "연결 응답 시간 초과",
    "connection · ConnectError": "연결 실패",
    "connection · ConnectTimeout": "연결 시간 초과",
    "connection · RemoteProtocolError": "연결 끊김",
    "time_limit · TIMEOUT": "시험 시간 초과",
    "browser · Error": "브라우저 오류",
    "browser · TimeoutError": "브라우저 응답 시간 초과",
    "browser login · BROWSER_LOGIN_FAILED": "브라우저 로그인 실패",
    "browser login · BROWSER_SCRIPT_NOT_RUNNING": "화면 스크립트 미동작",
    "browser heartbeat · QUEUE_TIMEOUT": "브라우저 대기열 시간 초과",
    "browser verify · BROWSER_CAPTCHA_FAILED": "브라우저 보안문자 실패",
    "browser captcha_image · BROWSER_CAPTCHA_IMAGE_NOT_LOADED": "보안문자 이미지 미표시",
    "browser confirm · BROWSER_CONFIRM_TIMEOUT": "브라우저 확정 응답 없음",
    "heartbeat · QUEUE_TIMEOUT": "대기열 시간 초과",
}
UUID_PATTERN = re.compile(r"\b([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
TILE_PATTERN = re.compile(r"^(?P<label>\D.*?)\s+(?P<value>\d[\d,.]*(?:ms|초|건|명|석|%|개|회)?(?:\s*/\s*\d[\d,.]*)?)$")
MILLISECONDS_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)ms$")
REPEATED_ITEM_PATTERN = re.compile(r"([^,·]+?)(?:, \1)+(?=,|$| ·)")  # "A, A, A" → "A"


@dataclass(frozen=True)
class SuiteTile:
    label: str
    value: str
    is_alert: bool = False


@dataclass
class SuiteResultView:
    headline: str = ""  # 결론 한 줄 · 실패 = FAIL 배지
    reason: str = ""  # 결론 옆 빨간 글 · 원인 요약
    tiles: list[SuiteTile] = field(default_factory=list)
    detail_lines: list[tuple[str, str]] = field(default_factory=list)  # 접기 안 · (fail | ref | info, 문구)
    raw_message: str = ""

    @property
    def is_summarized(self) -> bool:
        """결론 · 타일로 줄였으면 나머지와 원문은 접기 · 아니면 항목을 그대로"""
        return bool(self.headline or self.tiles)

    @property
    def is_empty(self) -> bool:
        return not (self.headline or self.tiles or self.detail_lines)


def humanize_text(text: str) -> str:
    """오류 코드 → 화면 문구 · 세션 번호 앞 8자리 · 같은 항목 반복 제거"""
    for code, title in FAILED_STEP_TITLES.items():
        text = text.replace(code, title)
    text = UUID_PATTERN.sub(lambda match: f"{match.group(1)}…", text)
    return REPEATED_ITEM_PATTERN.sub(r"\1", text)


def format_tile_value(value: str) -> str:
    """52147ms → 52.1초 · 1초 미만은 ms 그대로"""
    match = MILLISECONDS_PATTERN.match(value)
    if match and float(match.group(1)) >= 1000:
        return f"{float(match.group(1)) / 1000:.1f}초"
    return value


def is_alert_tile(label: str, value: str) -> bool:
    number = re.match(r"\d[\d,.]*", value)
    return any(word in label for word in ALERT_WORDS) and bool(number) and float(number.group().replace(",", "")) > 0


def parse_tile(segment: str) -> SuiteTile | None:
    match = TILE_PATTERN.match(segment.strip())
    if not match:
        return None
    label, value = match.group("label").strip(), match.group("value").strip()
    return SuiteTile(label, format_tile_value(value), is_alert_tile(label, value))


def split_headline(fail_texts: list[str]) -> tuple[str, str]:
    """FAIL 줄 첫 부분 = 결론 · 나머지 = 원인"""
    headline_parts, reason_parts = [], []
    for text in fail_texts:
        first, _, rest = text.partition(SEGMENT_SEPARATOR)
        headline_parts.append(first)
        if rest:
            reason_parts.append(rest)
    return SEGMENT_SEPARATOR.join(headline_parts), SEGMENT_SEPARATOR.join(reason_parts)


def build_generic_view(result: SuiteResult) -> SuiteResultView:
    view = SuiteResultView(raw_message=result.message)
    lines = [(kind, humanize_text(text)) for kind, text in split_message_lines(result.message)]
    if result.outcome in (SuiteOutcome.SKIPPED, SuiteOutcome.ERROR) and lines:
        view.headline = lines[0][1]  # 건너뜀 · 오류 사유는 문장 그대로
        lines = lines[1:]
    fail_texts = [text for kind, text in lines if kind == "fail"]
    view.headline, view.reason = split_headline(fail_texts) if fail_texts else (view.headline, "")
    for kind, text in lines:
        if kind != "info":
            if kind == "ref":
                view.detail_lines.append((kind, text))
            continue
        segments = text.split(SEGMENT_SEPARATOR)
        tiles = [parse_tile(segment) for segment in segments]
        if all(tiles) and len(view.tiles) + len(tiles) <= MAX_TILE_COUNT:
            view.tiles.extend(tiles)
        else:
            view.detail_lines.append((kind, text))
    if len(fail_texts) > 1 or (view.reason and len(view.reason) > 80):
        view.detail_lines[:0] = [("fail", text) for text in fail_texts]  # 긴 원인 · 전체 문구는 접기 안에
    return view


def build_booking_flow_view(result: SuiteResult) -> SuiteResultView:
    """예매 흐름 · 저장된 수치로 결론 · 타일 · 가장 느린 단계"""
    metrics = result.metrics
    success_count = int(metrics.get("booking_flow_success_count", 0))
    failure_count = int(metrics.get("booking_flow_failure_count", 0))
    planned_count = success_count + failure_count
    view = SuiteResultView(raw_message=result.message)
    lines = [(kind, humanize_text(text)) for kind, text in split_message_lines(result.message)]
    fail_texts = [text.split(SEGMENT_SEPARATOR + "예매 완료")[0] for kind, text in lines if kind == "fail"]  # 이전 기록 = 한 줄
    if result.outcome is SuiteOutcome.FAILED:
        view.headline = f"VU {planned_count}명 중 {failure_count}명 오류" if failure_count else (fail_texts[0] if fail_texts else "")
        view.reason = SEGMENT_SEPARATOR.join(text.replace(LIST_SEPARATOR, SEGMENT_SEPARATOR) for text in fail_texts)
    view.tiles = [
        SuiteTile("예매 완료", str(int(metrics.get("booking_flow_booked_count", 0)))),
        SuiteTile("매진", str(int(metrics.get("booking_flow_sold_out_count", 0)))),
        SuiteTile("오류", f"{failure_count}/{planned_count}", failure_count > 0),
    ]
    if "booking_flow_p95_latency_ms" in metrics:
        view.tiles.append(SuiteTile("전체 p95", format_tile_value(f"{metrics['booking_flow_p95_latency_ms']:.0f}ms")))
    step_p95 = result.details.get("step_p95_latency_ms") or {}
    if step_p95:
        slowest_step, slowest_ms = max(step_p95.items(), key=lambda item: item[1])
        view.tiles.append(SuiteTile("가장 느린 단계", f"{STEP_TITLES.get(slowest_step, slowest_step)} {slowest_ms / 1000:.1f}초", True))
        view.detail_lines.append(("info", "단계별 p95 · " + SEGMENT_SEPARATOR.join(
            f"{STEP_TITLES.get(step, step)} {value / 1000:.1f}초" for step, value in step_p95.items())))
    double_sold = int(metrics.get("booking_flow_double_sold_seat_count", 0))
    if double_sold:
        view.tiles.append(SuiteTile("중복 판매", f"{double_sold}석", True))
    view.detail_lines.extend((kind, text) for kind, text in lines if kind == "ref")
    return view


def build_suite_result_view(result: SuiteResult) -> SuiteResultView:
    if result.suite_name == BOOKING_FLOW_SUITE_NAME and result.metrics:
        return build_booking_flow_view(result)
    return build_generic_view(result)
