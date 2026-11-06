"""정답표 저장 · 읽기 · QA DB 전용 · Run 하나 = answer_keys 문서 하나"""
from pymongo.database import Database

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import AnswerKey, SessionKey
from ticket_guard_qa.qa_database.database import ANSWER_KEYS


class AnswerKeyRepository:
    def __init__(self, qa_database: Database) -> None:
        self.answer_keys = qa_database[ANSWER_KEYS]

    def save(self, run_id: str, answer_key: AnswerKey) -> None:
        entries = [{"session_key": key, "actor_type": actor_type.value} for key, actor_type in answer_key.items()]
        self.answer_keys.replace_one({"_id": run_id}, {"_id": run_id, "entries": entries}, upsert=True)

    def load(self, run_id: str) -> AnswerKey:
        document = self.answer_keys.find_one({"_id": run_id}) or {}
        return {SessionKey(entry["session_key"]): ActorType(entry["actor_type"]) for entry in document.get("entries", [])}
