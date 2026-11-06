"""시험 묶음 등록표 · 새 묶음은 여기에 한 줄 추가"""
from ticket_guard_qa.test_suites.booking_flow import BookingFlowSuite
from ticket_guard_qa.test_suites.event_contract import EventContractSuite
from ticket_guard_qa.test_suites.event_delivery import EventDeliverySuite
from ticket_guard_qa.test_suites.failure_recovery import FailureRecoverySuite
from ticket_guard_qa.test_suites.load_capacity import LoadCapacitySuite
from ticket_guard_qa.test_suites.pipeline_latency import PipelineLatencySuite
from ticket_guard_qa.test_suites.seat_concurrency import SeatConcurrencySuite
from ticket_guard_qa.test_suites.self_check import SelfCheckSuite
from ticket_guard_qa.test_suites.suite_interface import QaSuite
from ticket_guard_qa.test_suites.verdict_accuracy import VerdictAccuracySuite

REGISTERED_SUITES: tuple[QaSuite, ...] = (
    SelfCheckSuite(),
    EventContractSuite(),
    BookingFlowSuite(),
    EventDeliverySuite(),
    VerdictAccuracySuite(),
    PipelineLatencySuite(),
    SeatConcurrencySuite(),
    LoadCapacitySuite(),
    FailureRecoverySuite(),
)
SUITE_BY_NAME: dict[str, QaSuite] = {suite.suite_name: suite for suite in REGISTERED_SUITES}


def list_suites() -> list[QaSuite]:
    return list(REGISTERED_SUITES)


def get_suite(suite_name: str) -> QaSuite:
    if suite_name not in SUITE_BY_NAME:
        raise KeyError(f"없는 Suite: {suite_name} · 가능: {', '.join(SUITE_BY_NAME)}")
    return SUITE_BY_NAME[suite_name]
