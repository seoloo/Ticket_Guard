"""좌석 동시 확정 · 같은 좌석 동시 요청 → 예매 1건 · 초과 판매 0건"""
from ticket_guard_qa.domain.models import SuiteResult
from ticket_guard_qa.test_suites.suite_interface import SuiteContext


class SeatConcurrencySuite:
    suite_name = "seat_concurrency"
    title = "좌석 동시 확정"
    related_codes: tuple[str, ...] = ("E12", "E16", "E20")

    def run(self, context: SuiteContext) -> SuiteResult:
        # TODO(좌석 점유 결정 후): 같은 좌석으로 확정 요청 동시 전송 → bookings · inventory 확인
        raise NotImplementedError("좌석 점유 · Redis 미정 · AGENTS.md 11장")
