"""Phase 1 event contract. Only this adapter is replaced by Kafka later."""
from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
from uuid import uuid4


class EventPublisher(Protocol):
    def publish(self, event: dict) -> None: ...


class MockEventPublisher:
    def __init__(self):
        self.lock = RLock()
        self.records = deque(maxlen=1000)
        self.failed = 0

    def publish(self, event):
        with self.lock:
            self.records.append(event)

    def for_user(self, user):
        with self.lock:
            return [e for e in self.records if e['userId'] == user][-100:]


publisher = MockEventPublisher()
CLIENT_EVENTS = {'page_enter', 'page_exit', 'search_change', 'genre_change',
                 'show_select', 'schedule_select', 'seat_select', 'seat_cancel', 'quantity_change'}


def emit(user, event_type, attempt=None, **fields):
    now = datetime.now(timezone.utc).isoformat()
    event = dict(schemaVersion=1, eventId=str(uuid4()), eventType=event_type,
                 occurredAt=now, receivedAt=now, userId=user, bookingAttemptId=None,
                 pageInstanceId=None, showId=None, scheduleId=None,
                 requestSequence=None, result='success', errorCode=None, source='server')
    if attempt:
        event.update(bookingAttemptId=attempt['id'], pageInstanceId=attempt['page_id'],
                     showId=attempt['show_id'], scheduleId=attempt['show_id'] + '-evening')
    event.update(fields)
    try:
        publisher.publish(event)
    except Exception:
        publisher.failed += 1
    return event
