"""원본에서 화면에 필요한 최소 관측값만 추출한다. 본문은 상태 DB에 보관하지 않는다."""
import base64
import hashlib
import json
from datetime import datetime, timezone

STAGES = ('shows', 'detail', 'queue', 'captcha', 'select', 'complete', 'other')
LABELS = ('공연 목록', '상세·회차 선택', '대기열', '보안문자', '좌석·수량 선택', '예매 완료', '기타·미확인')
BUSINESS = {'queue_enter': 'queue', 'queue_register': 'queue', 'queue_admitted': 'captcha',
            'captcha_success': 'select', 'seat_select': 'select', 'quantity_change': 'select',
            'booking_confirm_success': 'complete'}


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('시각 문자열 누락')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('시간대 누락')
    return dt.timestamp()


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def decode(raw):
    item = json.loads(bytes(raw).decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('유효하지 않은 수')))
    if not isinstance(item, dict) or type(item.get('schemaVersion')) is not int or item['schemaVersion'] not in (1, 2):
        raise ValueError('지원하지 않는 이벤트 형식')
    if not isinstance(item.get('eventId'), str) or not isinstance(item.get('eventType'), str):
        raise ValueError('이벤트 식별자 누락')
    stamp(item.get('occurredAt')); stamp(item.get('receivedAt'))
    if not isinstance(item.get('details'), dict):
        raise ValueError('상세 정보 형식 오류')
    return item


def body(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('state') != 'captured':
        return {}
    value = snapshot.get('value')
    if snapshot.get('representation') == 'json' and isinstance(value, dict):
        return value
    if snapshot.get('representation') == 'text':
        try:
            value = json.loads(value)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            pass
    return {}


def project(event):
    d = event['details']; kind = event['eventType']
    req = body(d.get('request', {}).get('body'))
    res = body(d.get('response', {}).get('body'))
    browser = event.get('pageInstanceId') or req.get('pageId')
    anonymous = event.get('capture', {}).get('anonymousId')
    # 공유 계정은 합치지 않는다. 브라우저 식별자 없는 자료는 인원 계산에서 제외한다.
    actor = ('browser:' + browser) if browser else None
    attempt = event.get('bookingAttemptId') or req.get('attemptId')
    stage = None
    if kind == 'page_enter':
        stage = d.get('pageName', 'other')
    elif kind == 'server_request' and req.get('action') == 'heartbeat' and d.get('response', {}).get('status') == 200:
        stage = res.get('stage')
    elif event.get('source') == 'server' and event.get('result') == 'success':
        stage = BUSINESS.get(kind)
    if stage is not None and stage not in STAGES:
        stage = 'other'
    return {'id': event['eventId'], 'time': stamp(event['occurredAt']), 'received': stamp(event['receivedAt']),
            'actor': actor, 'view': event.get('pageViewId'), 'attempt': attempt,
            'stage': stage, 'kind': kind, 'source': event.get('source'),
            'exit': kind == 'page_exit' or (kind == 'page_lifecycle' and d.get('phase') == 'pagehide'),
            'cancel': kind == 'queue_cancel', 'timeout': kind == 'connection_timeout',
            'start': kind in ('queue_enter', 'queue_register') and event.get('source') == 'server',
            'success': kind == 'booking_confirm_success' and event.get('source') == 'server' and event.get('result') == 'success',
            'simulation': (event.get('isSimulation') is True) if event.get('schemaVersion') == 1 else None,
            'show': event.get('showId') or req.get('showId'),
            'schedule': event.get('scheduleId'),
            'fingerprint': hashlib.sha256(json.dumps({k: v for k, v in event.items() if k != 'receivedAt'}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()}


def chunk_part(event, max_bytes=8 * 1024 * 1024):
    d = event['details']
    if d.get('encoding') != 'base64-json-utf8' or type(d.get('count')) is not int or not 1 <= d['count'] <= 2048:
        raise ValueError('청크 형식 오류')
    if type(d.get('index')) is not int or not 0 <= d['index'] < d['count']:
        raise ValueError('청크 위치 오류')
    if type(d.get('totalBytes')) is not int or not 0 < d['totalBytes'] <= max_bytes:
        raise ValueError('청크 용량 초과')
    data = base64.b64decode(d['data'], validate=True)
    if len(data) > max_bytes:
        raise ValueError('청크 용량 초과')
    return d, data
