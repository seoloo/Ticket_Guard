"""JSON 보고서 · CI · 다른 도구가 읽는 용도"""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ticket_guard_qa.domain.models import RunSummary, run_config_to_dict


def summary_to_dict(summary: RunSummary) -> dict[str, Any]:
    return {
        "run_id": summary.run_id,
        "status": summary.status.value,
        "run_config": run_config_to_dict(summary.run_config),
        "started_at": summary.started_at.isoformat(),
        "finished_at": summary.finished_at.isoformat() if summary.finished_at else None,
        "passed_criteria_count": summary.passed_criteria_count,
        "criterion_results": [asdict(result) for result in summary.criterion_results],
        "suite_results": [
            {**asdict(result), "outcome": result.outcome.value} for result in summary.suite_results
        ],
    }


def write_json_report(summary: RunSummary, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{summary.run_id}.json"
    report_path.write_text(json.dumps(summary_to_dict(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path
