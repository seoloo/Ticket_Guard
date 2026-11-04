"""실행 기록 저장 · 읽기 · QA DB 전용"""
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome
from ticket_guard_qa.domain.models import (
    CriterionResult,
    RunConfig,
    RunSummary,
    SuiteResult,
    run_config_from_dict,
    run_config_to_dict,
)
from ticket_guard_qa.qa_database.tables import RunRecord, SuiteResultRecord

PREVIOUS_RUN_SEARCH_LIMIT = 50


class RunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_run(self, run_id: str, run_config: RunConfig, started_at: datetime) -> None:
        with self.session_factory.begin() as session:
            session.add(RunRecord(
                run_id=run_id,
                target_kind=run_config.target_kind.value,
                status=RunStatus.RUNNING.value,
                run_config=run_config_to_dict(run_config),
                criterion_results=[],
                started_at=started_at,
            ))

    def save_summary(self, summary: RunSummary) -> None:
        with self.session_factory.begin() as session:
            run_record = session.get(RunRecord, summary.run_id)
            run_record.status = summary.status.value
            run_record.finished_at = summary.finished_at
            run_record.criterion_results = [asdict(result) for result in summary.criterion_results]
            session.execute(delete(SuiteResultRecord).where(SuiteResultRecord.run_id == summary.run_id))
            session.add_all(
                SuiteResultRecord(
                    run_id=summary.run_id,
                    suite_name=result.suite_name,
                    outcome=result.outcome.value,
                    metrics=result.metrics,
                    message=result.message,
                    details=result.details,
                )
                for result in summary.suite_results
            )

    def get_summary(self, run_id: str) -> RunSummary | None:
        with self.session_factory() as session:
            run_record = session.get(RunRecord, run_id)
            if run_record is None:
                return None
            suite_records = session.scalars(
                select(SuiteResultRecord).where(SuiteResultRecord.run_id == run_id).order_by(SuiteResultRecord.id)
            )
            return RunSummary(
                run_id=run_record.run_id,
                run_config=run_config_from_dict(run_record.run_config),
                status=RunStatus(run_record.status),
                started_at=run_record.started_at,
                finished_at=run_record.finished_at,
                suite_results=[
                    SuiteResult(
                        record.suite_name, SuiteOutcome(record.outcome), record.metrics, record.message, record.details or {}
                    )
                    for record in suite_records
                ],
                criterion_results=[CriterionResult(**raw) for raw in run_record.criterion_results],
            )

    def list_recent_run_ids(self, limit: int = 10) -> list[str]:
        with self.session_factory() as session:
            return list(session.scalars(select(RunRecord.run_id).order_by(RunRecord.started_at.desc()).limit(limit)))

    def find_previous_same_config_summary(self, summary: RunSummary) -> RunSummary | None:
        """04 지난 실행과 비교 · 같은 조건 · 끝난 실행 중 바로 앞"""
        target_config = run_config_to_dict(summary.run_config)
        with self.session_factory() as session:
            candidate_records = session.scalars(
                select(RunRecord)
                .where(RunRecord.started_at < summary.started_at, RunRecord.finished_at.is_not(None))
                .order_by(RunRecord.started_at.desc())
                .limit(PREVIOUS_RUN_SEARCH_LIMIT)
            )
            previous_run_id = next(
                (record.run_id for record in candidate_records if record.run_config == target_config), None
            )
        return self.get_summary(previous_run_id) if previous_run_id else None

    def mark_unfinished_runs_as_error(self, finished_at: datetime) -> None:
        """프로그램이 실행 중에 꺼졌던 기록 정리 · 시작할 때 한 번"""
        with self.session_factory.begin() as session:
            session.execute(
                update(RunRecord)
                .where(RunRecord.status == RunStatus.RUNNING.value)
                .values(status=RunStatus.ERROR.value, finished_at=finished_at)
            )
