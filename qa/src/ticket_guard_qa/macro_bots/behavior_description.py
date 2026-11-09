"""행동 값 → 처음 보는 사람이 읽는 문장 · B1 카드 "예매 중 행동" · 값이 바뀌면 문장도 같이 바뀜"""
from dataclasses import dataclass

from ticket_guard_qa.domain.models import SessionBehavior

SAME_MOMENT_DEVIATION_MS = 100  # 이 편차 안 = 모든 세션이 같은 순간 시작
CROWDED_DEVIATION_MS = 1_000
MACHINE_RHYTHM_CV = 0.1  # 변동계수 0.1 미만 = 기계적 리듬
SLIGHTLY_IRREGULAR_CV = 0.3
INSTANT_START_MS = 50


@dataclass(frozen=True)
class BehaviorLine:
    step_title: str  # 예매 중 어느 순간인지
    headline: str
    detail: str


def format_seconds(milliseconds: float) -> str:
    """80 → 0.08초 · 1200 → 1.2초 · 3000 → 3초"""
    return f"{milliseconds / 1000:.3f}".rstrip("0").rstrip(".") + "초"


def describe_start_timing(behavior: SessionBehavior) -> BehaviorLine:
    mean_ms, deviation_ms = behavior.entry_delay_after_open_ms, behavior.entry_delay_deviation_ms
    if mean_ms < INSTANT_START_MS:
        headline = "예매 오픈과 동시에 예매하기 버튼 클릭"
    else:
        headline = f"예매 오픈 {format_seconds(mean_ms)} 뒤 예매하기 버튼 클릭"
    if deviation_ms < SAME_MOMENT_DEVIATION_MS:
        spread = "모든 세션이 거의 같은 순간 시작"
    elif deviation_ms < CROWDED_DEVIATION_MS:
        spread = "1초 안에 몰려서 시작"
    else:
        spread = "세션마다 시작 시각이 넓게 퍼짐"
    return BehaviorLine("예매 시작 시점", headline, f"세션마다 ±{format_seconds(deviation_ms)} 차이 · {spread}")


def describe_click_rhythm(behavior: SessionBehavior) -> BehaviorLine:
    mean_ms, deviation_ms = behavior.click_interval_mean_ms, behavior.click_interval_deviation_ms
    variation = deviation_ms / mean_ms if mean_ms else 0.0
    if variation < MACHINE_RHYTHM_CV:
        rhythm = "거의 일정한 기계적 리듬"
    elif variation < SLIGHTLY_IRREGULAR_CV:
        rhythm = "약간 불규칙한 리듬"
    else:
        rhythm = "사람처럼 불규칙한 리듬"
    return BehaviorLine("좌석 클릭 간격", f"좌석 클릭 사이 평균 {format_seconds(mean_ms)}",
                        f"클릭마다 ±{format_seconds(deviation_ms)} 차이 · {rhythm}")


def describe_parallel_sessions(behavior: SessionBehavior) -> BehaviorLine:
    count = behavior.sessions_per_device
    if count <= 1:
        return BehaviorLine("동시 예매 창", "기기 1대 · 예매 창 1개", "계정 1개로 예매 1건 진행")
    return BehaviorLine("동시 예매 창", f"기기 1대에서 예매 창 {count}개 동시 실행",
                        f"계정 {count}개 · 같은 기기 쿠키 · 같은 브라우저 정보 · 같은 순간 예매 시작")


def describe_browsing(behavior: SessionBehavior) -> BehaviorLine:
    count = behavior.browse_page_count
    if count == 0:
        return BehaviorLine("예매 전 화면 조회", "공연 목록 · 상세 화면 조회 없이 바로 예매", "예매 오픈 전 화면 이동 기록 없음")
    mean_ms, deviation_ms = behavior.page_dwell_mean_ms, behavior.page_dwell_deviation_ms
    variation = deviation_ms / mean_ms if mean_ms else 0.0
    dwell_pattern = "화면마다 거의 같은 체류 시간" if variation < MACHINE_RHYTHM_CV else "화면마다 다른 체류 시간"
    return BehaviorLine("예매 전 화면 조회", f"예매 오픈 전 공연 목록 · 상세 화면 {count}회 조회",
                        f"화면마다 평균 {format_seconds(mean_ms)} 체류 · ±{format_seconds(deviation_ms)} 차이 · {dwell_pattern}")


def describe_sold_out_reaction(behavior: SessionBehavior) -> BehaviorLine:
    count = behavior.sold_out_retry_count
    if count == 0:
        return BehaviorLine("매진 좌석 대응", "먼저 팔린 좌석이면 바로 포기", "다른 좌석 재시도 없음")
    delay_ms = behavior.sold_out_retry_delay_ms
    wait = f"재시도 전 {format_seconds(delay_ms)} 대기" if delay_ms else "대기 없이 즉시 재시도"
    return BehaviorLine("매진 좌석 대응", f"먼저 팔린 좌석이면 다른 좌석으로 최대 {count}회 재시도", wait)


def describe_browser_trace(behavior: SessionBehavior) -> BehaviorLine:
    if behavior.browser_trace_level >= 1:
        return BehaviorLine("브라우저 흔적", "화면 이벤트 · 브라우저 정보 함께 전송", "일반 PC 브라우저와 같은 접속 정보")
    return BehaviorLine("브라우저 흔적", "화면 이벤트 없이 예매 요청만 전송", "자동화 프로그램 기본 접속 정보 그대로")


def describe_behavior(behavior: SessionBehavior) -> list[BehaviorLine]:
    """예매 순서대로 · 화면 조회 → 예매 시작 → 좌석 클릭 → 매진 대응 → 동시 창 → 브라우저 흔적"""
    return [
        describe_browsing(behavior), describe_start_timing(behavior), describe_click_rhythm(behavior),
        describe_sold_out_reaction(behavior), describe_parallel_sessions(behavior), describe_browser_trace(behavior),
    ]
