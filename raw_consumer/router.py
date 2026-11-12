"""
[홍석환] 원본 이벤트의 컬렉션 라우팅 계약
이벤트 버전·종류에 따라 저장 컬렉션을 선택하고 미분류 사유를 제공한다.
동작 중인 소비자 그룹의 라우팅 계약은 임의로 바꾸지 않는다.
"""
import hashlib
import json

VERSION = 'raw-routing-v1'
GROUPS = {
    'behavior_events': ('page_enter', 'page_exit', 'search_change', 'genre_change',
                        'show_select', 'schedule_select', 'seat_select', 'seat_cancel',
                        'quantity_change', 'ui_interaction', 'page_lifecycle'),
    'booking_events': ('queue_enter', 'queue_register', 'queue_admitted', 'queue_cancel',
                       'connection_timeout', 'captcha_success', 'captcha_wrong',
                       'captcha_limit_reached', 'captcha_refresh', 'booking_confirm_request',
                       'booking_confirm_success', 'booking_confirm_fail', 'booking_access_rejected',
                       'booking_not_open', 'booking_confirm_rejected', 'booking_confirm_replayed'),
    'auth_events': ('login_success', 'login_fail'),
    'http_events': ('browser_request_start', 'browser_request_body', 'browser_response_headers',
                    'browser_request', 'server_request', 'server_response_headers'),
    'performance_events': ('resource_timing', 'navigation_timing', 'performance_entry'),
    'browser_errors': ('browser_error',),
    'collector_events': ('collector_limitation', 'collector_failure', 'scenario_executed'),
    'raw_chunks': ('capture_chunk',),
}
COLLECTIONS = tuple(GROUPS) + ('unclassified_events',)
ROUTES = {(v, kind): collection for v in (1, 2)
          for collection, kinds in GROUPS.items() for kind in kinds}


def fingerprint():
    # Fallback semantics are part of the version contract as well.
    encoded = json.dumps([VERSION, sorted((v, k, c) for (v, k), c in ROUTES.items()),
                          'utf8-json-strict-v1'], separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def route(value):
    """Only inspect routing fields; never replace or validate business payload."""
    meta = {'version': VERSION}
    reason = None
    if value is None:
        reason = 'null_payload'
    elif value == b'':
        reason = 'empty_payload'
    else:
        try:
            event = json.loads(value.decode('utf-8'),
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError, RecursionError):
            reason = 'parse_failed'
        else:
            if not isinstance(event, dict):
                reason = 'non_object_json'
            elif type(event.get('schemaVersion')) is not int or event['schemaVersion'] not in (1, 2):
                reason = 'unsupported_schema'
            elif not isinstance(event.get('eventType'), str):
                reason = 'invalid_event_type'
            else:
                target = ROUTES.get((event['schemaVersion'], event['eventType']))
                if target:
                    return target, meta
                reason = 'unknown_event_type'
    meta['reason'] = reason
    return 'unclassified_events', meta
