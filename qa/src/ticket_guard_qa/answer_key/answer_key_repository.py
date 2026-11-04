"""정답표 저장 · 읽기 · QA DB 전용"""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import AnswerKey, SessionKey
from ticket_guard_qa.qa_database.tables import AnswerKeyRecord


class AnswerKeyRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def save(self, run_id: str, answer_key: AnswerKey) -> None:
        with self.session_factory.begin() as session:
            session.execute(delete(AnswerKeyRecord).where(AnswerKeyRecord.run_id == run_id))
            session.add_all(
                AnswerKeyRecord(run_id=run_id, session_key=key, actor_type=actor_type.value)
                for key, actor_type in answer_key.items()
            )

    def load(self, run_id: str) -> AnswerKey:
        with self.session_factory() as session:
            records = session.scalars(select(AnswerKeyRecord).where(AnswerKeyRecord.run_id == run_id))
            return {SessionKey(record.session_key): ActorType(record.actor_type) for record in records}
