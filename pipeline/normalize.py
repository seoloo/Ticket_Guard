"""Validate Kafka event JSON and create sanitized Spark result documents."""
import json
import re
from datetime import datetime, timezone
from uuid import UUID

ALLOWED_EVENT_TYPES = {
    'page_enter', 'page_exit', 'search_change', 'genre_change', 'show_select',
    'schedule_select', 'seat_select', 'seat_cancel', 'quantity_change',
    'login_success', 'login_fail', 'queue_enter', 'queue_register',
    'queue_admitted', 'queue_cancel', 'connection_timeout', 'captcha_success',
    'captcha_wrong', 'captcha_refresh', 'captcha_limit_reached',
    'booking_access_rejected', 'booking_not_open', 'booking_confirm_request',
    'booking_confirm_success', 'booking_confirm_fail', 'booking_confirm_rejected',
    'booking_confirm_replayed', 'scenario_executed',
}
REQUIRED = ('schemaVersion', 'eventId', 'eventType', 'occurredAt', 'receivedAt')
SENSITIVE = re.compile(r'(password|passwd|token|secret|captcha.?answer|security.?code|authorization)', re.I)


def _utc(value, name):
    if not isinstance(value, str):
        raise ValueError(f'invalid_{name}')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'invalid_{name}') from None
    if parsed.tzinfo is None:
        raise ValueError(f'invalid_{name}')
    return parsed.astimezone(timezone.utc)


def _sanitize(value):
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items() if not SENSITIVE.search(str(key))}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def normalize(raw, transport):
    """Return (clean, quarantine), with sensitive input omitted from quarantine."""
    base = {'kafka': {key: transport[key] for key in ('topic', 'partition', 'offset', 'timestamp')}}
    try:
        if raw is None:
            raise ValueError('empty_value')
        event = json.loads(bytes(raw).decode('utf-8') if not isinstance(raw, str) else raw)
        if not isinstance(event, dict):
            raise ValueError('event_not_object')
        missing = [name for name in REQUIRED if not event.get(name)]
        if missing:
            raise ValueError('missing_' + '_'.join(missing))
        if event['schemaVersion'] not in ('1', '1.0', 1):
            raise ValueError('unsupported_schema_version')
        UUID(str(event['eventId']))
        if event['eventType'] not in ALLOWED_EVENT_TYPES:
            raise ValueError('unsupported_event_type')
        occurred = _utc(event['occurredAt'], 'occurredAt')
        received = _utc(event['receivedAt'], 'receivedAt')
        result = _sanitize(event)
        result['occurredAt'] = occurred
        result['receivedAt'] = received
        result['_id'] = str(event['eventId'])
        result['kafka'] = base['kafka']
        return result, None
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        reason = str(exc) or 'invalid_event'
        quarantine = {
            '_id': f"{transport['topic']}:{transport['partition']}:{transport['offset']}",
            'failureReason': reason[:120],
            'kafka': base['kafka'],
            'receivedAt': datetime.now(timezone.utc),
        }
        return None, quarantine
