"""Gold 반영 시간 · 격리 건수 · 기획서 21쪽 · Gold p95 10초 이하"""
from ticket_guard_qa.domain.enums import SuiteOutcome
from ticket_guard_qa.domain.models import SuiteResult
from ticket_guard_qa.scoring.latency_metrics import calculate_p95
from ticket_guard_qa.test_suites.suite_interface import SuiteContext


class PipelineLatencySuite:
    suite_name = "pipeline_latency"
    title = "Gold 반영 지연"
    related_codes: tuple[str, ...] = ()

    def run(self, context: SuiteContext) -> SuiteResult:
        # TODO(Kafka · Spark 연결 후): 시험 이벤트를 먼저 보내고 반영을 기다림
        pipeline_reader = context.system_target.pipeline_reader
        gold_latency_values_sec = pipeline_reader.read_gold_latency_sec(context.run_id)
        quarantined_event_count = pipeline_reader.count_quarantined_events(context.run_id)
        return SuiteResult(
            suite_name=self.suite_name,
            outcome=SuiteOutcome.PASSED,  # 측정 완료 · 합격은 합격 기준이 판단
            metrics={
                "gold_latency_p95_sec": calculate_p95(gold_latency_values_sec),
                "quarantined_event_count": float(quarantined_event_count),
            },
        )
