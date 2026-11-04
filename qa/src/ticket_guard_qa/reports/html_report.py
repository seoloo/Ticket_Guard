"""HTML 보고서 · 사람이 파일 하나로 보는 용도 · 04 화면과 같은 숫자"""
from html import escape
from pathlib import Path

from ticket_guard_qa.domain.models import RunSummary
from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA


def render_html_report(summary: RunSummary) -> str:
    title_by_criterion_id = {criterion.criterion_id: criterion.title for criterion in PASS_CRITERIA}
    criterion_rows = "".join(
        f"<tr><td>{escape(title_by_criterion_id[result.criterion_id])}</td>"
        f"<td>{'-' if result.measured_value is None else f'{result.measured_value:.2f}'}</td>"
        f"<td>{'측정 안 됨' if result.is_passed is None else ('통과' if result.is_passed else '실패')}</td></tr>"
        for result in summary.criterion_results
    )
    suite_rows = "".join(
        f"<tr><td>{escape(result.suite_name)}</td><td>{result.outcome.value}</td>"
        f"<td>{escape(result.message)}</td></tr>"
        for result in summary.suite_results
    )
    return (
        "<!doctype html><html lang='ko'><meta charset='utf-8'>"
        f"<title>{escape(summary.run_id)}</title>"
        f"<h1>{escape(summary.run_id)} · {summary.status.value}</h1>"
        f"<p>대상 {summary.run_config.target_kind.value} · 합격 기준 {summary.passed_criteria_count} / {len(PASS_CRITERIA)}</p>"
        f"<h2>합격 기준</h2><table border='1'><tr><th>기준</th><th>측정값</th><th>결과</th></tr>{criterion_rows}</table>"
        f"<h2>시험 묶음</h2><table border='1'><tr><th>묶음</th><th>결과</th><th>메시지</th></tr>{suite_rows}</table>"
        "</html>"
    )


def write_html_report(summary: RunSummary, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{summary.run_id}.html"
    report_path.write_text(render_html_report(summary), encoding="utf-8")
    return report_path
