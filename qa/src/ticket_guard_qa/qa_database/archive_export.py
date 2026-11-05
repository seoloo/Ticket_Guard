"""QA 보관본 내보내기 · 끝난 Run의 정답표 · 그때 쓴 봇 설정 → MongoDB 가져오기용 JSON · AGENTS.md 6장 · 수동 실행만"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ticket_guard_qa.domain.enums import ActorType, RunStatus
from ticket_guard_qa.macro_bots.behavior_fields import behavior_to_dict
from ticket_guard_qa.macro_bots.bot_profile_store import BotProfileStore
from ticket_guard_qa.qa_database.tables import AnswerKeyRecord, ArchiveExportRecord, RunRecord

ARCHIVE_SCHEMA_VERSION = 1
ARCHIVE_DATABASE_NAME = "ticketguard_qa_archive"  # 시스템 DB와 분리 · 판정 코드 읽기 금지
EXPORTABLE_RUN_STATUSES = (RunStatus.PASSED, RunStatus.FAILED)  # 실행 중 · 취소 · 오류 제외
RUNS_COLLECTION = "QA_ARCHIVE_RUNS"
ANSWER_KEYS_COLLECTION = "QA_ARCHIVE_ANSWER_KEYS"
BOT_VERSIONS_COLLECTION = "QA_ARCHIVE_BOT_VERSIONS"
MANIFEST_FILE_NAME = "manifest.json"


class ArchiveExportError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveBundle:
    archive_id: str
    exported_at: datetime
    recipient: str
    reason: str
    run_ids: tuple[str, ...]
    bot_version_numbers: dict[str, list[int]]  # 종류 → 내보낸 버전
    documents_by_collection: dict[str, list[dict[str, Any]]]


def to_mongo_date(moment: datetime) -> dict[str, str]:
    """mongoimport 확장 JSON 날짜 · UTC"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)  # SQLite는 시간대를 버림
    return {"$date": moment.astimezone(timezone.utc).isoformat()}


def create_archive_id(exported_at: datetime) -> str:
    return f"archive-{exported_at.astimezone(timezone.utc):%Y%m%d-%H%M%S}"


def build_archive_bundle(
    session_factory: sessionmaker[Session], run_ids: list[str], recipient: str, reason: str, exported_at: datetime
) -> ArchiveBundle:
    """끝난 Run만 · 정답표 · 그 Run이 쓴 봇 버전 · 다음 시험 계획은 넣지 않음"""
    if not run_ids:
        raise ArchiveExportError("Run 번호 필요")
    if not recipient.strip() or not reason.strip():
        raise ArchiveExportError("받는 사람 · 이유 필요 (내보내기 기록)")
    archive_id = create_archive_id(exported_at)
    bot_profile_store = BotProfileStore(session_factory)
    run_documents, answer_key_documents = [], []
    version_numbers_by_actor: dict[str, set[int]] = {}

    with session_factory() as session:
        for run_id in dict.fromkeys(run_ids):
            run_record = session.get(RunRecord, run_id)
            if run_record is None:
                raise ArchiveExportError(f"Run 없음 · {run_id}")
            if RunStatus(run_record.status) not in EXPORTABLE_RUN_STATUSES:
                raise ArchiveExportError(f"끝난 Run만 내보내기 · {run_id} · {run_record.status}")
            bot_version_numbers = run_record.run_config.get("bot_version_numbers", {})
            for actor_type, version_number in bot_version_numbers.items():
                version_numbers_by_actor.setdefault(actor_type, set()).add(version_number)
            run_documents.append({
                "_id": run_id, "schemaVersion": ARCHIVE_SCHEMA_VERSION, "archiveId": archive_id, "runId": run_id,
                "targetKind": run_record.target_kind, "status": run_record.status,
                "startedAt": to_mongo_date(run_record.started_at), "finishedAt": to_mongo_date(run_record.finished_at),
                "virtualUserCount": run_record.run_config.get("virtual_user_count"),
                "trafficMix": run_record.run_config.get("traffic_mix"),
                "randomSeed": run_record.run_config.get("random_seed"),  # 공개 후 같은 시드 재사용 금지
                "botVersionNumbers": bot_version_numbers,
            })
            answer_key_records = session.scalars(select(AnswerKeyRecord).where(AnswerKeyRecord.run_id == run_id))
            answer_key_documents += [
                {
                    "_id": f"{run_id}:{record.session_key}", "schemaVersion": ARCHIVE_SCHEMA_VERSION,
                    "archiveId": archive_id, "runId": run_id,
                    "bookingAttemptId": record.session_key, "actualActorType": record.actor_type,
                }
                for record in answer_key_records
            ]

    bot_version_documents = []
    for actor_type, version_numbers in sorted(version_numbers_by_actor.items()):
        for version_number in sorted(version_numbers):
            profile = bot_profile_store.load_registry_for_versions({actor_type: version_number}).get_profile(ActorType(actor_type))
            bot_version_documents.append({
                "_id": f"{actor_type}:v{version_number}", "schemaVersion": ARCHIVE_SCHEMA_VERSION,
                "archiveId": archive_id, "actorType": actor_type, "versionNumber": version_number,
                "behavior": behavior_to_dict(profile.behavior), "changeNote": profile.change_note,
            })

    return ArchiveBundle(
        archive_id=archive_id, exported_at=exported_at, recipient=recipient.strip(), reason=reason.strip(),
        run_ids=tuple(dict.fromkeys(run_ids)),
        bot_version_numbers={actor: sorted(numbers) for actor, numbers in sorted(version_numbers_by_actor.items())},
        documents_by_collection={
            RUNS_COLLECTION: run_documents,
            ANSWER_KEYS_COLLECTION: answer_key_documents,
            BOT_VERSIONS_COLLECTION: bot_version_documents,
        },
    )


def build_import_commands(archive_folder: Path) -> list[str]:
    """받는 쪽이 실행 · 같은 _id는 덮어쓰기 · 접속 주소는 받는 쪽 계정"""
    return [
        f'mongoimport --uri "<MONGO_URI>/{ARCHIVE_DATABASE_NAME}" --collection {collection} '
        f'--file "{archive_folder / f"{collection}.json"}" --jsonArray --mode upsert'
        for collection in (RUNS_COLLECTION, ANSWER_KEYS_COLLECTION, BOT_VERSIONS_COLLECTION)
    ]


def write_archive_files(bundle: ArchiveBundle, output_dir: Path) -> Path:
    archive_folder = output_dir / bundle.archive_id
    archive_folder.mkdir(parents=True, exist_ok=False)  # 같은 보관본 덮어쓰기 금지
    for collection, documents in bundle.documents_by_collection.items():
        (archive_folder / f"{collection}.json").write_text(json.dumps(documents, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest = {
        "archiveId": bundle.archive_id, "exportedAt": bundle.exported_at.isoformat(),
        "recipient": bundle.recipient, "reason": bundle.reason, "runIds": list(bundle.run_ids),
        "botVersionNumbers": bundle.bot_version_numbers, "targetDatabase": ARCHIVE_DATABASE_NAME,
        "documentCounts": {collection: len(documents) for collection, documents in bundle.documents_by_collection.items()},
        "importCommands": build_import_commands(archive_folder),
        "notice": "공개된 봇 버전 · 시드로 다시 잰 탐지율은 신뢰 불가 · 다음 시험은 새 봇 버전 · 새 시드",
    }
    (archive_folder / MANIFEST_FILE_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return archive_folder


def record_archive_export(session_factory: sessionmaker[Session], bundle: ArchiveBundle) -> None:
    with session_factory.begin() as session:
        session.add(ArchiveExportRecord(
            archive_id=bundle.archive_id, exported_at=bundle.exported_at, recipient=bundle.recipient,
            reason=bundle.reason, run_ids=list(bundle.run_ids), bot_version_numbers=bundle.bot_version_numbers,
        ))


def export_archive(
    session_factory: sessionmaker[Session], run_ids: list[str], recipient: str, reason: str, output_dir: Path,
    exported_at: datetime | None = None,
) -> Path:
    bundle = build_archive_bundle(session_factory, run_ids, recipient, reason, exported_at or datetime.now(timezone.utc))
    archive_folder = write_archive_files(bundle, output_dir)
    record_archive_export(session_factory, bundle)
    return archive_folder


def find_published_bot_versions(session_factory: sessionmaker[Session]) -> dict[str, set[int]]:
    """보관본으로 내보낸 봇 버전 · Run 시작 때 경고"""
    published: dict[str, set[int]] = {}
    with session_factory() as session:
        for record in session.scalars(select(ArchiveExportRecord)):
            for actor_type, version_numbers in record.bot_version_numbers.items():
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
