"""부하 · 판정 API p95 3초 이하 · 오류율 0% · 대기열 한도 T1 · T2"""
from ticket_guard_qa.domain.models import SuiteResult
from ticket_guard_qa.test_suites.suite_interface import SuiteContext


class LoadCapacitySuite:
    suite_name = "load_capacity"
    title = "부하"
    related_codes: tuple[str, ...] = ("T1", "T2")

    def run(self, context: SuiteContext) -> SuiteResult:
        # TODO(시험 계정 여러 개 생긴 후): traffic_generators/locust_traffic.py 실행 → p95 · 오류율
        raise NotImplementedError("개발 계정 2개뿐 · 부하 사용자 생성 불가 · AGENTS.md 5장")
