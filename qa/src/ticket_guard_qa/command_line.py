"""터미널 명령 · ticket-guard-qa run | list-suites | export-archive | dashboard · 종료 코드 0 통과 / 1 실패 / 2 오류"""
import argparse
import json
import sys

from ticket_guard_qa.domain.enums import RunStatus, TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.qa_database.archive_export import (
    DEFAULT_COLLECTION_NAMES,
    EXPORT_COLLECTIONS,
    MANIFEST_FILE_NAME,
    ArchiveExportError,
    export_archive,
)
from ticket_guard_qa.qa_database.database import connect_qa_database
from ticket_guard_qa.settings import load_settings
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService
from ticket_guard_qa.test_suites.suite_registry import list_suites

CONTAINER_HOST = "0.0.0.0"
CONTAINER_PORT = 8000
ARCHIVE_FOLDER_NAME = "archives"  # qa_data/archives · QA 볼륨 안 · 저장소 밖

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

    archive_command = commands.add_parser(
        "export-archive", help="QA 데이터 넘기기 · 끝난 Run → 컬렉션별 JSON (MongoDB 가져오기용) · QA 담당 승인 후에만"
    )
    archive_command.add_argument("--run", dest="run_ids", action="append", required=True, help="여러 번 지정 가능")
    archive_command.add_argument("--recipient", required=True, help="받는 사람 · 기록용")
    archive_command.add_argument("--reason", required=True, help="내보내는 이유 · 기록용")
    archive_command.add_argument(
        "--collection", dest="collection_names", action="append", choices=list(EXPORT_COLLECTIONS),
        help=f"여러 번 지정 가능 · 기본 {' · '.join(DEFAULT_COLLECTION_NAMES)} · 정답표 · 봇 설정은 직접 지정",
    )

    commands.add_parser("dashboard", help="QA 대시보드 띄우기 · 팀 compose 컨테이너 안에서만")
    return parser


def run_suites(arguments: argparse.Namespace) -> int:
    settings = load_settings()
    qa_database = connect_qa_database(settings.qa_database_url)
    run_service = RunService(settings, qa_database, RunProgressStream())
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


def export_archive_files(arguments: argparse.Namespace) -> int:
    settings = load_settings()
    qa_database = connect_qa_database(settings.qa_database_url)
    try:
        archive_folder = export_archive(
            qa_database, arguments.run_ids, arguments.recipient, arguments.reason,
            settings.report_output_dir.parent / ARCHIVE_FOLDER_NAME,
            collection_names=tuple(arguments.collection_names or DEFAULT_COLLECTION_NAMES),
        )
    except ArchiveExportError as error:
        print(f"내보내기 중단 · {error}")
        return 2
    manifest = json.loads((archive_folder / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
    print(f"{manifest['archiveId']} · Run {len(manifest['runIds'])}개 · {manifest['documentCounts']}")
    print(f"  폴더: {archive_folder}")
    if manifest["publishedBotVersionNumbers"]:
        print(f"  공개 처리된 봇 버전: {manifest['publishedBotVersionNumbers']} · 다음 시험은 새 버전 · 새 시드")
    print("  받는 쪽 가져오기 명령:")
    for command in manifest["importCommands"]:
        print(f"    {command}")
    return 0


def print_suites() -> int:
    for suite in list_suites():
        print(f"{suite.suite_name:<20} {suite.title}")
    return 0


def start_dashboard() -> int:
    import uvicorn  # dashboard 묶음 설치 시에만

    from ticket_guard_qa.dashboard.dashboard_app import create_dashboard_app

    # 컨테이너 안쪽 주소 · 밖에서는 팀 입구 127.0.0.1:8000/qa/로만 · AGENTS.md 4장
    uvicorn.run(create_dashboard_app(load_settings()), host=CONTAINER_HOST, port=CONTAINER_PORT)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    if arguments.command == "run":
        return run_suites(arguments)
    if arguments.command == "list-suites":
        return print_suites()
    if arguments.command == "export-archive":
        return export_archive_files(arguments)
    return start_dashboard()


if __name__ == "__main__":
    sys.exit(main())
