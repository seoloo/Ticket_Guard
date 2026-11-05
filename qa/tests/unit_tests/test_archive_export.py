"""QA 데이터 넘기기 · 끝난 Run만 · 기본은 결과 · 적발 목록 · 정답표 · 봇 설정은 직접 지정 · 기록 · 공개된 버전 경고"""
import json
from datetime import datetime, timezone

import pytest

from ticket_guard_qa.command_line import main
from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.domain.models import RunConfig
from ticket_guard_qa.qa_database import archive_export
from ticket_guard_qa.qa_database.archive_export import (
    ANSWER_KEYS_COLLECTION,
    BOT_VERSIONS_COLLECTION,
    FINDINGS_COLLECTION,
    MANIFEST_FILE_NAME,
    RUNS_COLLECTION,
    ArchiveExportError,
    export_archive,
    find_published_bot_versions,
)
from ticket_guard_qa.test_runs.run_progress_stream import RunProgressStream
from ticket_guard_qa.test_runs.run_service import RunService

EXPORTED_AT = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)
SENSITIVE_COLLECTION_NAMES = (RUNS_COLLECTION.name, ANSWER_KEYS_COLLECTION.name, BOT_VERSIONS_COLLECTION.name)


def run_fake_verdict_accuracy(qa_settings, session_factory, progress_stream=None):
    run_service = RunService(qa_settings, session_factory, progress_stream or RunProgressStream())
    return run_service.run_now(RunConfig(TargetKind.FAKE, ("verdict_accuracy",), virtual_user_count=40))


def read_collection(archive_folder, collection):
    return json.loads((archive_folder / f"{collection.name}.json").read_text(encoding="utf-8"))


def test_default_export_has_results_and_findings_only(qa_settings, session_factory, tmp_path):
    summary = run_fake_verdict_accuracy(qa_settings, session_factory)
    archive_folder = export_archive(session_factory, [summary.run_id], "db-team", "rule tuning", tmp_path, EXPORTED_AT)

    assert archive_folder.name == "archive-20261105-060000"
    assert sorted(path.name for path in archive_folder.iterdir()) == [
        "QA_ARCHIVE_FINDINGS.json", "QA_ARCHIVE_RUNS.json", MANIFEST_FILE_NAME,
    ]
    run_document = read_collection(archive_folder, RUNS_COLLECTION)[0]
    assert run_document["_id"] == summary.run_id and "$date" in run_document["finishedAt"]
    assert "bot_abd_detection_rate_percent" in run_document["metrics"]
    assert "randomSeed" not in run_document and "botVersionNumbers" not in run_document  # 시드 = 봇 다시 계산 가능
    findings = read_collection(archive_folder, FINDINGS_COLLECTION)
    assert len(findings) == run_document["missedBotCount"] + run_document["falsePositiveCount"]
    assert {finding["findingType"] for finding in findings} <= {"MISSED_BOT", "FALSE_POSITIVE"}
    assert all(finding["actualActorType"] for finding in findings)
    assert find_published_bot_versions(session_factory) == {}  # 봇 설정을 내보내지 않음 → 공개 아님


def test_sensitive_export_marks_bot_versions_and_next_run_warns(qa_settings, session_factory, tmp_path):
    summary = run_fake_verdict_accuracy(qa_settings, session_factory)
    archive_folder = export_archive(session_factory, [summary.run_id], "db-team", "model training", tmp_path,
                                    EXPORTED_AT, SENSITIVE_COLLECTION_NAMES)

    assert len(read_collection(archive_folder, ANSWER_KEYS_COLLECTION)) == 40
    assert read_collection(archive_folder, RUNS_COLLECTION)[0]["randomSeed"] == summary.run_config.random_seed
    bot_versions = read_collection(archive_folder, BOT_VERSIONS_COLLECTION)
    assert {document["_id"] for document in bot_versions} >= {"HUMAN:v1", "BOT_A:v1"}
    assert 1 in find_published_bot_versions(session_factory)["BOT_A"]

    progress_stream = RunProgressStream()
    next_summary = run_fake_verdict_accuracy(qa_settings, session_factory, progress_stream)
    messages = [message.text for message in progress_stream.read_after(next_summary.run_id, 0)]
    assert any(text.startswith("주의: 공개된 봇 버전 사용") for text in messages)


def test_new_field_needs_one_line(qa_settings, session_factory, tmp_path, monkeypatch):
    monkeypatch.setitem(archive_export.RUN_FIELDS, "suiteCount", lambda run: len(run.suite_records))  # 필드 추가 예시
    summary = run_fake_verdict_accuracy(qa_settings, session_factory)
    archive_folder = export_archive(session_factory, [summary.run_id], "db-team", "new field", tmp_path, EXPORTED_AT)
    assert read_collection(archive_folder, RUNS_COLLECTION)[0]["suiteCount"] == 1


def test_unfinished_run_and_missing_reason_are_rejected(qa_settings, session_factory, tmp_path):
    run_service = RunService(qa_settings, session_factory, RunProgressStream())
    run_service.run_repository.create_run("run-still-running", RunConfig(TargetKind.FAKE, ("self_check",)), EXPORTED_AT)
    with pytest.raises(ArchiveExportError, match="끝난 Run만"):
        export_archive(session_factory, ["run-still-running"], "db-team", "rule tuning", tmp_path)
    with pytest.raises(ArchiveExportError, match="이유"):
        export_archive(session_factory, ["run-still-running"], "db-team", " ", tmp_path)
    with pytest.raises(ArchiveExportError, match="컬렉션 확인"):
        export_archive(session_factory, ["run-still-running"], "db-team", "x", tmp_path, collection_names=("NOPE",))


def test_command_line_reports_missing_run(qa_settings, monkeypatch, capsys):
    monkeypatch.setenv("TICKET_GUARD_QA_QA_DATABASE_URL", qa_settings.qa_database_url)
    monkeypatch.setenv("TICKET_GUARD_QA_REPORT_OUTPUT_DIR", str(qa_settings.report_output_dir))
    exit_code = main(["export-archive", "--run", "run-missing", "--recipient", "db-team", "--reason", "check"])
    assert exit_code == 2
    assert "Run 없음" in capsys.readouterr().out
