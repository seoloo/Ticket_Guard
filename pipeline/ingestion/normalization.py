"""기존 적재 진입점의 누락된 최소 정규화. 새 흐름 모드는 이 경로를 사용하지 않는다."""
from datetime import datetime, timezone
from user_flow.events import decode


def normalize(raw, transport):
    try:
        event = decode(raw)
        if event['eventType'] == 'capture_chunk':
            return None, {'_id': transport['_id'], 'reason': 'chunk_requires_flow_mode'}
        clean = {key: event.get(key) for key in ('eventId', 'eventType', 'userId', 'bookingAttemptId',
                 'showId', 'scheduleId', 'result', 'errorCode', 'isSimulation', 'source')}
        for key in ('occurredAt', 'receivedAt'):
            clean[key] = datetime.fromisoformat(event[key].replace('Z', '+00:00'))
        clean.update(_id=event['eventId'], normalizedAt=datetime.now(timezone.utc))
        return clean, None
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None, {'_id': transport['_id'], 'reason': 'invalid_event'}
