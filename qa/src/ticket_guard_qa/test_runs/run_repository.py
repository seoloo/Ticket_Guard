"""실행 기록 저장 · 읽기 · QA DB 전용 · Run 하나 = runs 문서 하나 (Suite 결과 · 합격 기준 포함)"""
from dataclasses import asdict
from datetime import datetime
from typing import Any

from pymongo import DESCENDING
from pymongo.database import Database

from ticket_guard_qa.domain.enums import RunStatus, SuiteOutcome
from ticket_guard_qa.domain.models import (
    CriterionResult,
    RunConfig,
    RunSummary,
    SuiteResult,
    run_config_from_dict,
    run_config_to_dict,
)
from ticket_guard_qa.qa_database.database import RUNS, as_utc

PREVIOUS_RUN_SEARCH_LIMIT = 50


def suite_result_to_document(result: SuiteResult) -> dict[str, Any]:
    return {
        "suite_name": result.suite_name, "outcome": result.outcome.value, "metrics": result.metrics,
        "message": result.message, "details": result.details,
    }


def summary_from_document(document: dict[str, Any]) -> RunSummary:
    return RunSummary(
        run_id=document["_id"],
        run_config=run_config_from_dict(document["run_config"]),
        status=RunStatus(document["status"]),
        started_at=as_utc(document["started_at"]),
        finished_at=as_utc(document.get("finished_at")),
        suite_results=[
            SuiteResult(suite["suite_name"], SuiteOutcome(suite["outcome"]), suite.get("metrics") or {},
                        suite.get("message") or "", suite.get("details") or {})
            for suite in document.get("suite_results", [])
        ],
        criterion_results=[CriterionResult(**raw) for raw in document.get("criterion_results", [])],
    )


class RunRepository:
    def __init__(self, qa_database: Database) -> None:
        self.runs = qa_database[RUNS]

    def create_run(self, run_id: str, run_config: RunConfig, started_at: datetime) -> None:
        self.runs.insert_one({
            "_id": run_id,
            "target_kind": run_config.target_kind.value,
            "status": RunStatus.RUNNING.value,
            "run_config": run_config_to_dict(run_config),
            "suite_results": [],
            "criterion_results": [],
            "started_at": started_at,
            "finished_at": None,
        })

    def save_summary(self, summary: RunSummary) -> None:
        self.runs.update_one({"_id": summary.run_id}, {"$set": {
            "status": summary.status.value,
            "finished_at": summary.finished_at,
            "suite_results": [suite_result_to_document(result) for result in summary.suite_results],
            "criterion_results": [asdict(result) for result in summary.criterion_results],
        }})

    def get_summary(self, run_id: str) -> RunSummary | None:
        document = self.runs.find_one({"_id": run_id})
        return summary_from_document(document) if document else None

    def list_recent_run_ids(self, limit: int = 10) -> list[str]:
        return [document["_id"] for document in self.runs.find({}, {"_id": 1}).sort("started_at", DESCENDING).limit(limit)]

    def find_latest_finished_summary_with_suite(self, suite_name: str) -> RunSummary | None:
        """B1 카드 · 가장 최근에 끝난 실행 중 이 묶음 결과가 있는 것 · 측정 완료(PASSED)만"""
        document = self.runs.find_one(
            {
                "finished_at": {"$ne": None},
                "suite_results": {"$elemMatch": {"suite_name": suite_name, "outcome": SuiteOutcome.PASSED.value}},
            },
            sort=[("started_at", DESCENDING)],
        )
        return summary_from_document(document) if document else None

    def find_previous_same_config_summary(self, summary: RunSummary) -> RunSummary | None:
        """04 지난 실행과 비교 · 같은 조건 · 끝난 실행 중 바로 앞"""
        target_config = run_config_to_dict(summary.run_config)
        candidates = self.runs.find(
            {"started_at": {"$lt": summary.started_at}, "finished_at": {"$ne": None}},
        ).sort("started_at", DESCENDING).limit(PREVIOUS_RUN_SEARCH_LIMIT)
        document = next((candidate for candidate in candidates if candidate["run_config"] == target_config), None)
        return summary_from_document(document) if document else None

    def mark_unfinished_runs_as_error(self, finished_at: datetime) -> None:
        """프로그램이 실행 중에 꺼졌던 기록 정리 · 시작할 때 한 번"""
        self.runs.update_many(
            {"status": RunStatus.RUNNING.value},
            {"$set": {"status": RunStatus.ERROR.value, "finished_at": finished_at}},
        )
