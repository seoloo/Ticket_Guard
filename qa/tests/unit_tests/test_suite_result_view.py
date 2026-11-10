"""04 Suite 자체 검증 · 결론 한 줄 · 핵심 수치 타일 · 상세 접기 · 지난 Live Run 실제 문구 기준"""
from ticket_guard_qa.dashboard.suite_result_view import build_suite_result_view, humanize_text
from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import SuiteResult

OLD_BOOKING_MESSAGE = (  # 이전 기록 · 실패 원인과 결과가 한 줄
    "FAIL: connection · ReadTimeout 15건, time_limit · TIMEOUT 7건, browser · Error 2건 · 예매 완료 37 · 매진 139 · 오류 24 / VU 200"
    " · 전체 p95 52147ms · 로그인 3133ms · 좌석 클릭 30225ms · 시험 데이터 초기화"
)
EVENT_DELIVERY_MESSAGE = "\n".join([
    "FAIL: 서버 이벤트 누락 27건 · af0be4dc-5771-4472-81cd-aece64835b89 · booking_confirm_fail",
    "좌석 클릭 이벤트 1680/1680",
    "서버 이벤트 2738 · 누락 27 · 중복 0",
    "전달 지연 p95 3330ms",
    "참고: connection · ReadTimeout 38건",
])


def build_booking_result(message: str) -> SuiteResult:
    return SuiteResult(
        "booking_flow", SuiteOutcome.FAILED,
        metrics={"booking_flow_success_count": 176.0, "booking_flow_failure_count": 24.0, "booking_flow_booked_count": 37.0,
                 "booking_flow_sold_out_count": 139.0, "booking_flow_double_sold_seat_count": 0.0,
                 "booking_flow_p95_latency_ms": 52147.0},
        message=message,
        details={"step_p95_latency_ms": {"login": 3133.0, "seat_select": 30225.0, "confirm": 11625.0}},
    )


def test_booking_flow_shows_conclusion_causes_and_slowest_step():
    view = build_suite_result_view(build_booking_result(OLD_BOOKING_MESSAGE))

    assert view.headline == "VU 200명 중 24명 오류"
    assert view.reason == "연결 응답 시간 초과 15건 · 시험 시간 초과 7건 · 브라우저 오류 2건"  # 코드 → 화면 문구 · 결과 수치 제외
    tiles = {tile.label: tile for tile in view.tiles}
    assert (tiles["오류"].value, tiles["오류"].is_alert) == ("24/200", True)
    assert tiles["전체 p95"].value == "52.1초"
    assert (tiles["가장 느린 단계"].value, tiles["가장 느린 단계"].is_alert) == ("좌석 클릭 30.2초", True)
    assert view.detail_lines[0] == ("info", "단계별 p95 · 로그인 3.1초 · 좌석 클릭 30.2초 · 확정 11.6초")
    assert view.raw_message == OLD_BOOKING_MESSAGE  # 원문은 접기 안에 그대로


def test_other_suites_split_fail_line_into_headline_and_number_tiles():
    view = build_suite_result_view(SuiteResult("event_delivery", SuiteOutcome.FAILED, message=EVENT_DELIVERY_MESSAGE))

    assert view.headline == "서버 이벤트 누락 27건"
    assert view.reason == "af0be4dc… · booking_confirm_fail"  # 세션 번호 앞 8자리
    assert [(tile.label, tile.value, tile.is_alert) for tile in view.tiles] == [
        ("좌석 클릭 이벤트", "1680/1680", False), ("서버 이벤트", "2738", False), ("누락", "27", True),
        ("중복", "0", False), ("전달 지연 p95", "3.3초", False),
    ]
    assert view.detail_lines == [("ref", "연결 응답 시간 초과 38건")]


def test_repeated_error_samples_are_merged():
    assert humanize_text("서버 오류 · 연결 실패 73건 · connection · ReadTimeout, connection · ReadTimeout, connection · ReadTimeout") \
        == "서버 오류 · 연결 실패 73건 · 연결 응답 시간 초과"


def test_skipped_suite_shows_reason_sentence_without_tiles():
    view = build_suite_result_view(SuiteResult("raw_ingest", SuiteOutcome.SKIPPED, message="원본 DB 읽기 미설정 · 읽기 전용 계정"))
    assert (view.headline, view.tiles, view.detail_lines) == ("원본 DB 읽기 미설정 · 읽기 전용 계정", [], [])


def test_list_only_message_stays_as_lines_and_empty_message_is_empty():
    view = build_suite_result_view(SuiteResult("event_contract", SuiteOutcome.PASSED, message="SKIP: kafka_malformed_json(토픽 주입 미설정)"))
    assert not view.headline and not view.tiles and view.detail_lines == [("info", "SKIP: kafka_malformed_json(토픽 주입 미설정)")]
    assert build_suite_result_view(SuiteResult("self_check", SuiteOutcome.PASSED)).is_empty
