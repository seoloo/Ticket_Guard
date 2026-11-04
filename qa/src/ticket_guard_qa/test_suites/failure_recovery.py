"""장애 복구 · 서비스 중지 → 다시 시작 → 정상 처리까지 · 60초 이하"""
from ticket_guard_qa.domain.models import SuiteResult
from ticket_guard_qa.test_suites.suite_interface import SuiteContext


class FailureRecoverySuite:
    suite_name = "failure_recovery"
    title = "장애 복구"
    related_codes: tuple[str, ...] = ()

    def run(self, context: SuiteContext) -> SuiteResult:
        # TODO(파이프라인 연결 후): Spark 중지 → 시작 → checkpoint 이후 중복 · 누락 없이 처리될 때까지 시간
        raise NotImplementedError("복구할 파이프라인 없음 · AGENTS.md 5장")
