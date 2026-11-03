"""터미널 명령 · ticket-guard-qa run | list-suites | dashboard · 종료 코드 0 통과 / 1 실패 / 2 오류"""
import argparse
import sys

from ticket_guard_qa.domain.enums import RunStatus, TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.qa_database.database import create_qa_database_engine, create_session_factory
from ticket_guard_qa.settings import load_settings
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService
from ticket_guard_qa.test_suites.suite_registry import list_suites

EXIT_CODE_BY_STATUS = {
    RunStatus.PASSED: 0,
    RunStatus.FAILED: 1,
    RunStatus.ERROR: 2,
    RunStatus.CANCELLED: 2,
}


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ticket-guard-qa", description="티켓가드 자동화 QA")
    commands = parser.add_subparsers(dest="command", required=True)

    run_command = commands.add_parser("run", help="시험 실행")
    run_command.add_argument("--suite", dest="suite_names", action="append", required=True, help="여러 번 지정 가능")
    run_command.add_argument("--target", dest="target_kind", type=TargetKind, choices=list(TargetKind))
    run_command.add_argument("--users", dest="virtual_user_count", type=int, default=200)
    run_command.add_argument("--duration-sec", dest="duration_sec", type=int, default=300)

    commands.add_parser("list-suites", help="시험 묶음 목록")

    dashboard_command = commands.add_parser("dashboard", help="QA 대시보드 띄우기 · 기본 포트 8800")
    dashboard_command.add_argument("--port", dest="dashboard_port", type=int)
    return parser


def run_suites(arguments: argparse.Namespace) -> int:
    settings = load_settings()
    session_factory = create_session_factory(create_qa_database_engine(settings.qa_database_url))
    run_service = RunService(settings, session_factory, RunProgressStream())
    run_config = RunConfig(
        target_kind=arguments.target_kind or settings.target_kind,
        suite_names=tuple(arguments.suite_names),
        virtual_user_count=arguments.virtual_user_count,
        duration_sec=arguments.duration_sec,
        random_seed=settings.random_seed,
    )
    summary = run_service.run_now(run_config)
    print(f"{summary.run_id} · {summary.status.value} · 대상 {run_config.target_kind.value}")
    for result in summary.suite_results:
        print(f"  {result.outcome.value:<8} {result.suite_name} {result.message}")
    print(f"  보고서: {settings.report_output_dir / summary.run_id}.html")
    return EXIT_CODE_BY_STATUS[summary.status]


def print_suites() -> int:
    for suite in list_suites():
        print(f"{suite.suite_name:<20} {suite.title}")
    return 0


def start_dashboard(arguments: argparse.Namespace) -> int:
    import uvicorn  # dashboard 묶음 설치 시에만

    from ticket_guard_qa.dashboard.dashboard_app import create_dashboard_app

    settings = load_settings()
    port = arguments.dashboard_port or settings.dashboard_port  # 8000 금지 · AGENTS.md 4장
    uvicorn.run(create_dashboard_app(settings), host=settings.dashboard_host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    if arguments.command == "run":
        return run_suites(arguments)
    if arguments.command == "list-suites":
        return print_suites()
    return start_dashboard(arguments)


if __name__ == "__main__":
    sys.exit(main())
