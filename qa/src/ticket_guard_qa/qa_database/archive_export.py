"""QA 데이터 넘기기 · 필요할 때만 · 끝난 Run → 컬렉션별 JSON (MongoDB 가져오기용) · 시스템 DB에는 쓰지 않음 · AGENTS.md 6장

새 필드 = 아래 *_FIELDS에 한 줄 · 새 컬렉션 = ExportCollection 하나 + EXPORT_COLLECTIONS에 등록
"""
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo.database import Database

from ticket_guard_qa.domain.enums import ActorType, RunStatus
from ticket_guard_qa.macro_bots.behavior_fields import behavior_to_dict
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileStore
from ticket_guard_qa.macro_bots.bot_profiles import BotProfile
from ticket_guard_qa.qa_database.database import ANSWER_KEYS, ARCHIVE_EXPORTS, RUNS, as_utc

ARCHIVE_SCHEMA_VERSION = 1
ARCHIVE_DATABASE_NAME = "ticketguard_qa_archive"  # QA 전달용 · 시스템 DB(ticketguard)와 분리 · 판정 코드 읽기 금지
EXPORTABLE_RUN_STATUSES = (RunStatus.PASSED, RunStatus.FAILED)  # 실행 중 · 취소 · 오류 제외
VERDICT_ACCURACY_SUITE_NAME = "verdict_accuracy"  # 놓친 봇 · 오탐 목록이 있는 결과
MANIFEST_FILE_NAME = "manifest.json"

MISSED_BOT_FINDING = "MISSED_BOT"
FALSE_POSITIVE_FINDING = "FALSE_POSITIVE"


class ArchiveExportError(ValueError):
    pass


@dataclass(frozen=True)
class RunSnapshot:
    """Run 하나의 QA DB 기록 · 필드 함수가 읽는 재료"""
    document: dict[str, Any]  # runs 문서
    answer_key: dict[str, str]  # bookingAttemptId → actor_type

    @property
    def run_id(self) -> str:
        return self.document["_id"]

    @property
    def run_config(self) -> dict[str, Any]:
        return self.document["run_config"]

    @property
    def criterion_results(self) -> list[dict[str, Any]]:
        return self.document.get("criterion_results", [])

    def suite_details(self, suite_name: str) -> dict[str, Any]:
        suites = self.document.get("suite_results", [])
        return next((suite.get("details") or {} for suite in suites if suite["suite_name"] == suite_name), {})

    def merged_metrics(self) -> dict[str, float]:
        suites = self.document.get("suite_results", [])
        return {name: value for suite in suites for name, value in (suite.get("metrics") or {}).items()}


@dataclass(frozen=True)
class FindingRow:
    run: RunSnapshot
    booking_attempt_id: str
    finding_type: str


@dataclass(frozen=True)
class AnswerKeyRow:
    run: RunSnapshot
    booking_attempt_id: str
    actor_type: str


FieldReader = Callable[[Any], Any]


@dataclass(frozen=True)
class ExportCollection:
    name: str
    is_sensitive: bool  # True = 정답표 · 봇 설정 · 내보내면 그 봇 버전은 공개됨
    id_reader: FieldReader  # 같은 건 다시 보내도 덮어쓰기 (upsert)
    fields: dict[str, FieldReader]
    list_rows: Callable[["ExportSource"], list[Any]]


def to_mongo_date(moment: datetime | None) -> dict[str, str] | None:
    """mongoimport 확장 JSON 날짜 · UTC"""
    if moment is None:
        return None
    return {"$date": as_utc(moment).isoformat()}


RUN_FIELDS: dict[str, FieldReader] = {
    "runId": lambda run: run.run_id,
    "targetKind": lambda run: run.document["target_kind"],
    "status": lambda run: run.document["status"],
    "startedAt": lambda run: to_mongo_date(run.document["started_at"]),
    "finishedAt": lambda run: to_mongo_date(run.document.get("finished_at")),
    "virtualUserCount": lambda run: run.run_config.get("virtual_user_count"),
    "trafficMix": lambda run: run.run_config.get("traffic_mix"),
    "metrics": lambda run: run.merged_metrics(),
    "criterionResults": lambda run: run.criterion_results,
    "passedCriteriaCount": lambda run: sum(result.get("is_passed") is True for result in run.criterion_results),
    "missedBotCount": lambda run: run.suite_details(VERDICT_ACCURACY_SUITE_NAME).get("missed_bot_count"),
    "falsePositiveCount": lambda run: run.suite_details(VERDICT_ACCURACY_SUITE_NAME).get("false_positive_count"),
    "ruleHitCountByRuleId": lambda run: run.suite_details(VERDICT_ACCURACY_SUITE_NAME).get("rule_hit_count_by_rule_id"),
}
# 정답표 · 봇 설정을 함께 내보낼 때만 · 시드가 있으면 VU 순서로 봇을 다시 계산할 수 있음
RUN_SENSITIVE_FIELDS: dict[str, FieldReader] = {
    "randomSeed": lambda run: run.run_config.get("random_seed"),
    "botVersionNumbers": lambda run: run.run_config.get("bot_version_numbers", {}),
}

FINDING_FIELDS: dict[str, FieldReader] = {
    "runId": lambda row: row.run.run_id,
    "bookingAttemptId": lambda row: row.booking_attempt_id,  # 시스템 SESSION_VERDICTS · SESSION_FEATURES와 연결
    "findingType": lambda row: row.finding_type,
    "actualActorType": lambda row: row.run.answer_key.get(row.booking_attempt_id),
}

ANSWER_KEY_FIELDS: dict[str, FieldReader] = {
    "runId": lambda row: row.run.run_id,
    "bookingAttemptId": lambda row: row.booking_attempt_id,
    "actualActorType": lambda row: row.actor_type,
}

BOT_VERSION_FIELDS: dict[str, FieldReader] = {
    "actorType": lambda profile: profile.actor_type.value,
    "versionNumber": lambda profile: profile.version_number,
    "behavior": lambda profile: behavior_to_dict(profile.behavior),
    "changeNote": lambda profile: profile.change_note,
}


def list_finding_rows(source: "ExportSource") -> list[FindingRow]:
    rows = []
    for run in source.runs:
        details = run.suite_details(VERDICT_ACCURACY_SUITE_NAME)
        rows += [FindingRow(run, key, MISSED_BOT_FINDING) for key in details.get("missed_bot_session_keys", [])]
        rows += [FindingRow(run, key, FALSE_POSITIVE_FINDING) for key in details.get("false_positive_session_keys", [])]
    return rows


def list_answer_key_rows(source: "ExportSource") -> list[AnswerKeyRow]:
    return [AnswerKeyRow(run, key, actor_type) for run in source.runs for key, actor_type in run.answer_key.items()]


RUNS_COLLECTION = ExportCollection(
    "QA_ARCHIVE_RUNS", False, lambda run: run.run_id, RUN_FIELDS, lambda source: source.runs,
)
FINDINGS_COLLECTION = ExportCollection(
    "QA_ARCHIVE_FINDINGS", False, lambda row: f"{row.run.run_id}:{row.booking_attempt_id}",
    FINDING_FIELDS, list_finding_rows,
)
ANSWER_KEYS_COLLECTION = ExportCollection(
    "QA_ARCHIVE_ANSWER_KEYS", True, lambda row: f"{row.run.run_id}:{row.booking_attempt_id}",
    ANSWER_KEY_FIELDS, list_answer_key_rows,
)
BOT_VERSIONS_COLLECTION = ExportCollection(
    "QA_ARCHIVE_BOT_VERSIONS", True, lambda profile: f"{profile.actor_type.value}:v{profile.version_number}",
    BOT_VERSION_FIELDS, lambda source: source.bot_profiles,
)
EXPORT_COLLECTIONS: dict[str, ExportCollection] = {
    collection.name: collection
    for collection in (RUNS_COLLECTION, FINDINGS_COLLECTION, ANSWER_KEYS_COLLECTION, BOT_VERSIONS_COLLECTION)
}
DEFAULT_COLLECTION_NAMES = (RUNS_COLLECTION.name, FINDINGS_COLLECTION.name)  # 결과 · 적발 목록 · 봇 설정 없음


@dataclass(frozen=True)
class ExportSource:
    runs: list[RunSnapshot]
    bot_profiles: list[BotProfile]  # 그 Run들이 쓴 봇 버전


@dataclass(frozen=True)
class ArchiveBundle:
    archive_id: str
    exported_at: datetime
    recipient: str
    reason: str
    run_ids: tuple[str, ...]
    collection_names: tuple[str, ...]
    published_bot_version_numbers: dict[str, list[int]]  # 민감 컬렉션을 내보낸 경우만
    documents_by_collection: dict[str, list[dict[str, Any]]]


def create_archive_id(exported_at: datetime) -> str:
    return f"archive-{exported_at.astimezone(timezone.utc):%Y%m%d-%H%M%S}"


def load_export_source(qa_database: Database, run_ids: list[str]) -> ExportSource:
    runs: list[RunSnapshot] = []
    version_numbers_by_actor: dict[str, set[int]] = {}
    for run_id in run_ids:
        document = qa_database[RUNS].find_one({"_id": run_id})
        if document is None:
            raise ArchiveExportError(f"Run 없음 · {run_id}")
        if RunStatus(document["status"]) not in EXPORTABLE_RUN_STATUSES:
            raise ArchiveExportError(f"끝난 Run만 내보내기 · {run_id} · {document['status']}")
        answer_document = qa_database[ANSWER_KEYS].find_one({"_id": run_id}) or {}
        answer_key = {entry["session_key"]: entry["actor_type"] for entry in answer_document.get("entries", [])}
        runs.append(RunSnapshot(document, answer_key))
        for actor_type, version_number in document["run_config"].get("bot_version_numbers", {}).items():
            version_numbers_by_actor.setdefault(actor_type, set()).add(version_number)
    bot_profile_store = BotProfileStore(qa_database)
    bot_profiles = [
        bot_profile_store.load_registry_for_versions({actor_type: version_number}).get_profile(ActorType(actor_type))
        for actor_type, version_numbers in sorted(version_numbers_by_actor.items())
        for version_number in sorted(version_numbers)
    ]
    return ExportSource(runs, bot_profiles)


def build_documents(collection: ExportCollection, source: ExportSource, archive_id: str,
                    extra_fields: dict[str, FieldReader] | None = None) -> list[dict[str, Any]]:
    fields = {**collection.fields, **(extra_fields or {})}
    return [
        {
            "_id": collection.id_reader(row), "schemaVersion": ARCHIVE_SCHEMA_VERSION, "archiveId": archive_id,
            **{field_name: read_field(row) for field_name, read_field in fields.items()},
        }
        for row in collection.list_rows(source)
    ]


def build_archive_bundle(
    qa_database: Database, run_ids: list[str], recipient: str, reason: str, exported_at: datetime,
    collection_names: tuple[str, ...] = DEFAULT_COLLECTION_NAMES,
) -> ArchiveBundle:
    """끝난 Run만 · 고른 컬렉션만 · 다음 시험 계획은 넣지 않음"""
    if not run_ids:
        raise ArchiveExportError("Run 번호 필요")
    if not recipient.strip() or not reason.strip():
        raise ArchiveExportError("받는 사람 · 이유 필요 (내보내기 기록)")
    unknown_names = [name for name in collection_names if name not in EXPORT_COLLECTIONS]
    if unknown_names or not collection_names:
        raise ArchiveExportError(f"컬렉션 확인 · {', '.join(unknown_names) or '없음'} · 가능: {', '.join(EXPORT_COLLECTIONS)}")

    unique_run_ids = tuple(dict.fromkeys(run_ids))
    unique_collection_names = tuple(dict.fromkeys(collection_names))
    source = load_export_source(qa_database, list(unique_run_ids))
    archive_id = create_archive_id(exported_at)
    is_sensitive = any(EXPORT_COLLECTIONS[name].is_sensitive for name in unique_collection_names)
    documents_by_collection = {
        name: build_documents(
            EXPORT_COLLECTIONS[name], source, archive_id,
            RUN_SENSITIVE_FIELDS if name == RUNS_COLLECTION.name and is_sensitive else None,
        )
        for name in unique_collection_names
    }
    published: dict[str, list[int]] = {}
    if is_sensitive:
        for profile in source.bot_profiles:
            published.setdefault(profile.actor_type.value, []).append(profile.version_number)
    return ArchiveBundle(archive_id, exported_at, recipient.strip(), reason.strip(), unique_run_ids,
                         unique_collection_names, published, documents_by_collection)


def build_import_commands(archive_folder: Path, collection_names: tuple[str, ...]) -> list[str]:
    """받는 쪽이 실행 · 같은 _id는 덮어쓰기 · 접속 주소는 받는 쪽 계정"""
    return [
        f'mongoimport --uri "<MONGO_URI>/{ARCHIVE_DATABASE_NAME}" --collection {name} '
        f'--file "{archive_folder / f"{name}.json"}" --jsonArray --mode upsert'
        for name in collection_names
    ]


def write_archive_files(bundle: ArchiveBundle, output_dir: Path) -> Path:
    archive_folder = output_dir / bundle.archive_id
    archive_folder.mkdir(parents=True, exist_ok=False)  # 같은 보관본 덮어쓰기 금지
    for name, documents in bundle.documents_by_collection.items():
        (archive_folder / f"{name}.json").write_text(json.dumps(documents, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest = {
        "archiveId": bundle.archive_id, "exportedAt": bundle.exported_at.isoformat(),
        "recipient": bundle.recipient, "reason": bundle.reason, "runIds": list(bundle.run_ids),
        "collections": list(bundle.collection_names), "targetDatabase": ARCHIVE_DATABASE_NAME,
        "documentCounts": {name: len(documents) for name, documents in bundle.documents_by_collection.items()},
        "publishedBotVersionNumbers": bundle.published_bot_version_numbers,
        "importCommands": build_import_commands(archive_folder, bundle.collection_names),
    }
    if bundle.published_bot_version_numbers:
        manifest["notice"] = "공개된 봇 버전 · 시드로 다시 잰 탐지율은 신뢰 불가 · 다음 시험은 새 봇 버전 · 새 시드"
    (archive_folder / MANIFEST_FILE_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return archive_folder


def record_archive_export(qa_database: Database, bundle: ArchiveBundle) -> None:
    qa_database[ARCHIVE_EXPORTS].insert_one({
        "_id": bundle.archive_id, "exported_at": bundle.exported_at, "recipient": bundle.recipient,
        "reason": bundle.reason, "run_ids": list(bundle.run_ids), "collection_names": list(bundle.collection_names),
        "bot_version_numbers": bundle.published_bot_version_numbers,
    })


def export_archive(
    qa_database: Database, run_ids: list[str], recipient: str, reason: str, output_dir: Path,
    exported_at: datetime | None = None, collection_names: tuple[str, ...] = DEFAULT_COLLECTION_NAMES,
) -> Path:
    bundle = build_archive_bundle(qa_database, run_ids, recipient, reason,
                                  exported_at or datetime.now(timezone.utc), collection_names)
    archive_folder = write_archive_files(bundle, output_dir)
    record_archive_export(qa_database, bundle)
    return archive_folder


def find_published_bot_versions(qa_database: Database) -> dict[str, set[int]]:
    """정답표 · 봇 설정을 내보낸 봇 버전 · Run 시작 때 경고"""
    published: dict[str, set[int]] = {}
    for record in qa_database[ARCHIVE_EXPORTS].find({}, {"bot_version_numbers": 1}):
        for actor_type, version_numbers in record.get("bot_version_numbers", {}).items():
            published.setdefault(actor_type, set()).update(version_numbers)
    return published


def find_published_versions_in_use(
    published: dict[str, set[int]], bot_version_numbers: dict[str, int]
) -> list[str]:
    return [
        f"{actor_type} v{version_number}"
        for actor_type, version_number in sorted(bot_version_numbers.items())
        if version_number in published.get(actor_type, set())
    ]
