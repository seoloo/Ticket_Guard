"""봇 버전 저장 · 읽기 · QA DB 전용 · 봇 설정값은 시스템 · 다른 브랜치로 내보내지 않음 (AGENTS.md 2장)"""
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.macro_bots.behavior_fields import behavior_to_dict
from ticket_guard_qa.macro_bots.bot_profiles import (
    DEFAULT_BEHAVIOR_BY_ACTOR_TYPE,
    DEFAULT_VERSION_NUMBER,
    BotProfile,
    BotProfileRegistry,
    build_default_profiles,
)
from ticket_guard_qa.qa_database.tables import BotVersionRecord


class BotProfileLockedError(Exception):
    pass


def profile_from_record(record: BotVersionRecord) -> BotProfile:
    actor_type = ActorType(record.actor_type)
    stored_behavior = record.profile.get("behavior", {})
    default_values = behavior_to_dict(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[actor_type])
    known_values = {name: stored_behavior[name] for name in default_values if name in stored_behavior}
    return BotProfile(
        actor_type=actor_type,
        behavior=SessionBehavior(**{**default_values, **known_values}),  # 저장 뒤 생긴 행동 값 = 기본값
        version_number=record.version_number,
        change_note=record.profile.get("change_note", ""),
        saved_at=record.saved_at,
    )


class BotProfileStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def load_current_registry(self) -> BotProfileRegistry:
        """종류마다 가장 최근 버전 · 저장 기록 없으면 기본값 v1"""
        latest_by_actor_type = {profile.actor_type: profile for profile in build_default_profiles()}
        with self.session_factory() as session:
            latest_versions = (
                select(BotVersionRecord.actor_type, func.max(BotVersionRecord.version_number).label("version_number"))
                .group_by(BotVersionRecord.actor_type)
                .subquery()
            )
            records = session.scalars(
                select(BotVersionRecord).join(
                    latest_versions,
                    (BotVersionRecord.actor_type == latest_versions.c.actor_type)
                    & (BotVersionRecord.version_number == latest_versions.c.version_number),
                )
            )
            for record in records:
                profile = profile_from_record(record)
                latest_by_actor_type[profile.actor_type] = profile
        return BotProfileRegistry(tuple(latest_by_actor_type.values()))

    def load_registry_for_versions(self, version_numbers: Mapping[str, int]) -> BotProfileRegistry:
        """실행 당시 버전 그대로 · B3 · 다시 계산할 때"""
        profiles = []
        for default_profile in build_default_profiles():
            wanted_version = version_numbers.get(default_profile.actor_type.value, DEFAULT_VERSION_NUMBER)
            profiles.append(self.find_version(default_profile.actor_type, wanted_version) or default_profile)
        return BotProfileRegistry(tuple(profiles))

    def find_version(self, actor_type: ActorType, version_number: int) -> BotProfile | None:
        if version_number == DEFAULT_VERSION_NUMBER:
            return None
        with self.session_factory() as session:
            record = session.scalar(
                select(BotVersionRecord).where(
                    BotVersionRecord.actor_type == actor_type.value, BotVersionRecord.version_number == version_number
                )
            )
            return profile_from_record(record) if record else None

    def list_version_history(self, actor_type: ActorType) -> list[BotProfile]:
        """최신 먼저 · 마지막 줄은 기본값 v1"""
        with self.session_factory() as session:
            records = session.scalars(
                select(BotVersionRecord)
                .where(BotVersionRecord.actor_type == actor_type.value)
                .order_by(BotVersionRecord.version_number.desc())
            )
            saved_profiles = [profile_from_record(record) for record in records]
        default_profile = next(profile for profile in build_default_profiles() if profile.actor_type is actor_type)
        return [*saved_profiles, default_profile]

    def save_new_version(
        self, actor_type: ActorType, behavior: SessionBehavior, change_note: str, saved_at: datetime
    ) -> BotProfile:
        if BotProfile(actor_type, behavior).type_info.is_locked:
            raise BotProfileLockedError("읽기 전용 프로필")
        with self.session_factory.begin() as session:
            latest_version = session.scalar(
                select(func.max(BotVersionRecord.version_number)).where(BotVersionRecord.actor_type == actor_type.value)
            )
            record = BotVersionRecord(
                actor_type=actor_type.value,
                version_number=(latest_version or DEFAULT_VERSION_NUMBER) + 1,
                profile={"behavior": behavior_to_dict(behavior), "change_note": change_note.strip()},
                saved_at=saved_at,
            )
            session.add(record)
            session.flush()
            return profile_from_record(record)
