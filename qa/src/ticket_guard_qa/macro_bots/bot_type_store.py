"""화면에서 추가한 봇 유형 저장 · QA DB bot_types · 시스템 · 다른 브랜치로 내보내지 않음 (AGENTS.md 2장)"""
import string
from datetime import datetime
from typing import Any

from pymongo.database import Database

from ticket_guard_qa.domain.enums import BUILT_IN_ACTOR_TYPES, ActorType
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.macro_bots.behavior_fields import behavior_to_dict
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE
from ticket_guard_qa.macro_bots.bot_catalog import (
    BOT_CATEGORY_BY_ID,
    BUILT_IN_BOT_TYPES,
    CUSTOM_BOT_COLORS,
    BotStatus,
    BotTypeInfo,
    build_custom_bot_type,
    replace_custom_bot_types,
)
from ticket_guard_qa.qa_database.database import BOT_TYPES, as_utc

CUSTOM_ACTOR_PREFIX = "BOT_"
MAX_DETECTION_SIGNAL_COUNT = 3
RESERVED_SHORT_NAMES = {info.short_name for info in BUILT_IN_BOT_TYPES}


class BotTypeInputError(ValueError):
    pass


def generate_short_names():
    """E, F, … Z, AA, AB, … · 기본 A ~ D와 겹치지 않게"""
    letters = string.ascii_uppercase
    for letter in letters:
        yield letter
    for first in letters:
        for second in letters:
            yield first + second


def bot_type_from_document(document: dict[str, Any]) -> BotTypeInfo:
    stored_behavior = document.get("initial_behavior", {})
    default_values = behavior_to_dict(DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.HUMAN])  # 저장 뒤 생긴 행동 값 = 정상 기본값
    default_values.update({name: stored_behavior[name] for name in default_values if name in stored_behavior})
    return build_custom_bot_type(
        actor_type=ActorType(document["actor_type"]),
        display_name=document["display_name"],
        short_name=document["short_name"],
        purpose=document["purpose"],
        category_id=document["category_id"],
        color_hex=document["color_hex"],
        detection_signals=tuple(document.get("detection_signals", ())),
        detection_target_id=document.get("detection_target_id"),
        status=BotStatus(document.get("status", BotStatus.DRAFT.value)),
        initial_behavior=SessionBehavior(**default_values),
    )


class BotTypeStore:
    def __init__(self, qa_database: Database) -> None:
        self.bot_types = qa_database[BOT_TYPES]

    def load_custom_types(self) -> tuple[BotTypeInfo, ...]:
        return tuple(bot_type_from_document(document) for document in self.bot_types.find().sort("created_at", 1))

    def refresh_catalog(self) -> tuple[BotTypeInfo, ...]:
        """bot_catalog 목록을 QA DB와 맞춤 · 화면 · 실행 시작 전에 호출"""
        custom_types = self.load_custom_types()
        replace_custom_bot_types(custom_types)
        return custom_types

    def find_document(self, actor_type: ActorType | str) -> dict[str, Any] | None:
        return self.bot_types.find_one({"actor_type": str(actor_type)})

    def pick_next_short_name(self) -> str:
        used = RESERVED_SHORT_NAMES | {document["short_name"] for document in self.bot_types.find({}, {"short_name": 1})}
        used_ids = {actor_type.value for actor_type in BUILT_IN_ACTOR_TYPES}
        return next(name for name in generate_short_names()
                    if name not in used and f"{CUSTOM_ACTOR_PREFIX}{name}" not in used_ids)

    def create_draft(self, base_info: BotTypeInfo, base_behavior: SessionBehavior, created_at: datetime) -> BotTypeInfo:
        """1단계 · 시작 봇 복사 · 이름 · 분류는 2단계에서 · 작성 중 = Run 제외"""
        short_name = self.pick_next_short_name()
        custom_count = self.bot_types.count_documents({})
        document = {
            "_id": f"{CUSTOM_ACTOR_PREFIX}{short_name}",
            "actor_type": f"{CUSTOM_ACTOR_PREFIX}{short_name}",
            "short_name": short_name,
            "display_name": f"새 봇 {short_name}",
            "purpose": "",
            "category_id": base_info.category_id if BOT_CATEGORY_BY_ID[base_info.category_id].is_selectable else "request_automation",
            "color_hex": CUSTOM_BOT_COLORS[custom_count % len(CUSTOM_BOT_COLORS)],
            "detection_signals": [],
            "detection_target_id": base_info.detection_target_id or "bot_abd_detection",
            "status": BotStatus.DRAFT.value,
            "base_actor_type": base_info.actor_type.value,
            "initial_behavior": behavior_to_dict(base_behavior),
            "created_at": created_at,
            "updated_at": created_at,
        }
        self.bot_types.insert_one(document)
        self.refresh_catalog()
        return bot_type_from_document(document)

    def update_fields(self, actor_type: ActorType | str, fields: dict[str, Any], updated_at: datetime) -> BotTypeInfo:
        self.bot_types.update_one({"actor_type": str(actor_type)}, {"$set": {**fields, "updated_at": updated_at}})
        self.refresh_catalog()
        return bot_type_from_document(self.find_document(actor_type))

    def update_identity(self, actor_type: ActorType | str, display_name: str, purpose: str, category_id: str,
                        updated_at: datetime) -> BotTypeInfo:
        """2단계 · 이름 · 한 줄 정의 · 수법 분류"""
        display_name, purpose = display_name.strip(), purpose.strip()
        if not display_name or len(display_name) > 30:
            raise BotTypeInputError("봇 이름 · 1 ~ 30자")
        if not purpose or len(purpose) > 80:
            raise BotTypeInputError("한 줄 정의 · 1 ~ 80자")
        category = BOT_CATEGORY_BY_ID.get(category_id)
        if category is None or not category.is_selectable:
            raise BotTypeInputError("공격 수법 분류 · 선택 오류")
        return self.update_fields(actor_type, {"display_name": display_name, "purpose": purpose, "category_id": category_id},
                                  updated_at)

    def update_initial_behavior(self, actor_type: ActorType | str, behavior: SessionBehavior, updated_at: datetime) -> BotTypeInfo:
        """3단계 · 작성 중에만 · 검증 중부터는 B2 버전 저장"""
        return self.update_fields(actor_type, {"initial_behavior": behavior_to_dict(behavior)}, updated_at)

    def update_detection(self, actor_type: ActorType | str, signals: list[str], detection_target_id: str | None,
                         allowed_target_ids: set[str], updated_at: datetime) -> BotTypeInfo:
        """4단계 · 탐지 흔적 1 ~ 3줄 · 합격 기준 묶음"""
        cleaned = [signal.strip() for signal in signals if signal.strip()][:MAX_DETECTION_SIGNAL_COUNT]
        if not cleaned:
            raise BotTypeInputError("탐지 흔적 · 1줄 이상")
        if any(len(signal) > 60 for signal in cleaned):
            raise BotTypeInputError("탐지 흔적 · 줄마다 60자 이하")
        if detection_target_id is not None and detection_target_id not in allowed_target_ids:
            raise BotTypeInputError("합격 기준 · 선택 오류")
        return self.update_fields(actor_type, {"detection_signals": cleaned, "detection_target_id": detection_target_id},
                                  updated_at)

    def change_status(self, actor_type: ActorType | str, status: BotStatus, updated_at: datetime) -> BotTypeInfo:
        document = self.find_document(actor_type)
        if document is None:
            raise BotTypeInputError("추가한 봇 유형 아님")
        if status is not BotStatus.DRAFT and (not document["purpose"] or not document.get("detection_signals")):
            raise BotTypeInputError("이름 · 한 줄 정의 · 탐지 흔적 입력 후 상태 변경")
        return self.update_fields(actor_type, {"status": status.value}, updated_at)

    def read_created_at(self, actor_type: ActorType | str) -> datetime | None:
        document = self.find_document(actor_type)
        return as_utc(document["created_at"]) if document else None
