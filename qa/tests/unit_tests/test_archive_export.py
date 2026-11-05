"""QA 보관본 내보내기 · 끝난 Run만 · 정답표 · 그때 쓴 봇 버전 · 기록 · 공개된 버전 경고"""
import json
from datetime import datetime, timezone

import pytest

from ticket_guard_qa.command_line import main
from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.qa_database.archive_export import (
    ANSWER_KEYS_COLLECTION,
    BOT_VERSIONS_COLLECTION,
    MANIFEST_FILE_NAME,
    RUNS_COLLECTION,
    ArchiveExportError,
    export_archive,
    find_published_bot_versions,
)
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService

EXPORTED_AT = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)


def run_fake_verdict_accuracy(qa_settings, session_factory, progress_stream=None):
    run_service = RunService(qa_settings, session_factory, progress_stream or RunProgressStream())
    return run_service.run_now(RunConfig(TargetKind.FAKE, ("verdict_accuracy",), virtual_user_count=20))


def read_collection(archive_folder, collection):
    return json.loads((archive_folder / f"{collection}.json").read_text(encoding="utf-8"))


def test_finished_run_exports_answer_key_and_bot_versions(qa_settings, session_factory, tmp_path):
    summary = run_fake_verdict_accuracy(qa_settings, session_factory)
    archive_folder = export_archive(session_factory, [summary.run_id], "db-team", "rule tuning", tmp_path, EXPORTED_AT)

    assert archive_folder.name == "archive-20261105-060000"
    run_document = read_collection(archive_folder, RUNS_COLLECTION)[0]
    assert run_document["_id"] == summary.run_id and "$date" in run_document["finishedAt"]
    answer_keys = read_collection(archive_folder, ANSWER_KEYS_COLLECTION)
    assert len(answer_keys) == 20
    assert answer_keys[0]["_id"] == f"{summary.run_id}:{answer_keys[0]['bookingAttemptId']}"
    bot_versions = read_collection(archive_folder, BOT_VERSIONS_COLLECTION)
    assert {document["_id"] for document in bot_versions} >= {"HUMAN:v1", "BOT_A:v1"}
    assert "click_interval_mean_ms" in bot_versions[0]["behavior"]
    manifest = json.loads((archive_folder / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
    assert manifest["recipient"] == "db-team" and len(manifest["importCommands"]) == 3


def test_export_is_recorded_and_next_run_warns(qa_settings, session_factory, tmp_path):
    summary = run_fake_verdict_accuracy(qa_settings, session_factory)
    export_archive(session_factory, [summary.run_id], "db-team", "rule tuning", tmp_path, EXPORTED_AT)
    assert 1 in find_published_bot_versions(session_factory)["BOT_A"]

    progress_stream = RunProgressStream()
    next_summary = run_fake_verdict_accuracy(qa_settings, session_factory, progress_stream)
    messages = [message.text for message in progress_stream.read_after(next_summary.run_id, 0)]
    assert any(text.startswith("주의: 공개된 봇 버전 사용") for text in messages)


def test_unfinished_run_and_missing_reason_are_rejected(qa_settings, session_factory, tmp_path):
    run_service = RunService(qa_settings, session_factory, RunProgressStream())
    run_service.run_repository.create_run("run-still-running", RunConfig(TargetKind.FAKE, ("self_check",)), EXPORTED_AT)
    with pytest.raises(ArchiveExportError, match="끝난 Run만"):
        export_archive(session_factory, ["run-still-running"], "db-team", "rule tuning", tmp_path)
    with pytest.raises(ArchiveExportError, match="이유"):
        export_archive(session_factory, ["run-still-running"], "db-team", " ", tmp_path)
    assert find_published_bot_versions(session_factory) == {}


def test_command_line_reports_missing_run(qa_settings, monkeypatch, capsys):
    monkeypatch.setenv("TICKET_GUARD_QA_QA_DATABASE_URL", qa_settings.qa_database_url)
    monkeypatch.setenv("TICKET_GUARD_QA_REPORT_OUTPUT_DIR", str(qa_settings.report_output_dir))
    exit_code = main(["export-archive", "--run", "run-missing", "--recipient", "db-team", "--reason", "check"])
    assert exit_code == 2
    assert "Run 없음" in capsys.readouterr().out
