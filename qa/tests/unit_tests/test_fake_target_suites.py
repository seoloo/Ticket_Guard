from pathlib import Path

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.domain.enums import SuiteOutcome, TargetKind, VerdictStage
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.settings import QA_ROOT_DIR
from ticket_guard_qa.system_targets import fake_system
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.test_suites.event_contract import EventContractSuite
from ticket_guard_qa.test_suites.self_check import SelfCheckSuite
from ticket_guard_qa.test_suites.suite_interface import SuiteContext


def build_context(qa_database, case_data_dir: Path = QA_ROOT_DIR / "case_data") -> SuiteContext:
    return SuiteContext(
        run_id="run-test",
        run_config=RunConfig(TargetKind.FAKE, ("self_check",)),
        system_target=build_fake_system_target(),
        answer_key_repository=AnswerKeyRepository(qa_database),
        case_data_dir=case_data_dir,
        report_progress=lambda text, **fields: None,
    )


def test_self_check_passes_with_correct_scoring(qa_database):
    result = SelfCheckSuite().run(build_context(qa_database))
    assert result.outcome is SuiteOutcome.PASSED, result.message


def test_self_check_fails_when_fixed_responses_change(qa_database, monkeypatch):
    changed_verdicts = dict(fake_system.FIXED_SESSION_VERDICTS)
    changed_verdicts[next(iter(changed_verdicts))] = VerdictStage.HOLD
    monkeypatch.setattr(fake_system, "FIXED_SESSION_VERDICTS", changed_verdicts)
    result = SelfCheckSuite().run(build_context(qa_database))
    assert result.outcome is SuiteOutcome.FAILED


def test_event_contract_passes_on_fake_target(qa_database):
    result = EventContractSuite().run(build_context(qa_database))
    assert result.outcome is SuiteOutcome.PASSED, result.message
    assert result.message == ""  # 브라우저 · 예매 확정 · 토픽 사례 전부 실행 · 건너뜀 없음
