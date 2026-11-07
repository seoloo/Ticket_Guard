"""봇 버전 저장 · 읽기 · QA DB 전용 · 봇 설정값은 시스템 · 다른 브랜치로 내보내지 않음 (AGENTS.md 2장)"""
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pymongo import DESCENDING
from pymongo.database import Database

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
from ticket_guard_qa.qa_database.database import BOT_VERSIONS, as_utc


class BotProfileLockedError(Exception):
    pass


def profile_from_document(document: dict[str, Any]) -> BotProfile:
    actor_type = ActorType(document["actor_type"])
    stored_behavior = document["profile"].get("behavior", {})
    default_values = behavior_to_dict(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[actor_type])
    known_values = {name: stored_behavior[name] for name in default_values if name in stored_behavior}
    return BotProfile(
        actor_type=actor_type,
        behavior=SessionBehavior(**{**default_values, **known_values}),  # 저장 뒤 생긴 행동 값 = 기본값
        version_number=document["version_number"],
        change_note=document["profile"].get("change_note", ""),
        saved_at=as_utc(document["saved_at"]),
    )


class BotProfileStore:
    def __init__(self, qa_database: Database) -> None:
        self.bot_versions = qa_database[BOT_VERSIONS]

    def load_current_registry(self) -> BotProfileRegistry:
        """종류마다 가장 최근 버전 · 저장 기록 없으면 기본값 v1"""
        latest_by_actor_type = {profile.actor_type: profile for profile in build_default_profiles()}
        for actor_type in latest_by_actor_type:
            document = self.bot_versions.find_one({"actor_type": actor_type.value}, sort=[("version_number", DESCENDING)])
            if document:
                latest_by_actor_type[actor_type] = profile_from_document(document)
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
        document = self.bot_versions.find_one({"actor_type": actor_type.value, "version_number": version_number})
        return profile_from_document(document) if document else None

    def list_version_history(self, actor_type: ActorType) -> list[BotProfile]:
        """최신 먼저 · 마지막 줄은 기본값 v1"""
        documents = self.bot_versions.find({"actor_type": actor_type.value}).sort("version_number", DESCENDING)
        saved_profiles = [profile_from_document(document) for document in documents]
        default_profile = next(profile for profile in build_default_profiles() if profile.actor_type is actor_type)
        return [*saved_profiles, default_profile]

    def save_new_version(
        self, actor_type: ActorType, behavior: SessionBehavior, change_note: str, saved_at: datetime
    ) -> BotProfile:
        if BotProfile(actor_type, behavior).type_info.is_locked:
            raise BotProfileLockedError("읽기 전용 프로필")
        latest = self.bot_versions.find_one({"actor_type": actor_type.value}, sort=[("version_number", DESCENDING)])
        version_number = (latest["version_number"] if latest else DEFAULT_VERSION_NUMBER) + 1
        document = {
            "_id": f"{actor_type.value}:v{version_number}",  # 종류 · 버전 고유 · 동시 저장 시 두 번째는 거절
            "actor_type": actor_type.value,
            "version_number": version_number,
            "profile": {"behavior": behavior_to_dict(behavior), "change_note": change_note.strip()},
            "saved_at": saved_at,
        }
        self.bot_versions.insert_one(document)
        return profile_from_document(document)
