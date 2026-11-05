"""Executable schema v1: reject unknown fields, including sensitive payloads."""
import json
import re
from datetime import datetime
from uuid import UUID

CLIENT_EVENTS = {'page_enter', 'page_exit', 'search_change', 'genre_change', 'show_select', 'schedule_select', 'seat_select', 'seat_cancel', 'quantity_change'}
SERVER_EVENTS = {'login_success', 'login_fail', 'queue_enter', 'queue_register', 'queue_cancel', 'connection_timeout', 'captcha_success', 'captcha_wrong', 'booking_confirm_request', 'booking_confirm_success', 'booking_confirm_fail', 'queue_admitted', 'booking_access_rejected', 'booking_not_open', 'captcha_limit_reached', 'captcha_refresh', 'booking_confirm_rejected', 'booking_confirm_replayed', 'scenario_executed'}
PAGES = {'login', 'shows', 'detail', 'queue', 'captcha', 'select', 'complete', 'history'}
SCENARIOS = {'open_later', 'open_now', 'admit', 'expire', 'four_wrong', 'collision', 'shortage', 'disconnect', 'verification_outage', 'repeat_confirm', 'old_confirm'}
FIELDS = {'schemaVersion','eventId','eventType','occurredAt','receivedAt','source','userId','pageInstanceId','pageViewId','bookingAttemptId','showId','scheduleId','requestSequence','result','errorCode','isSimulation','scenarioName','details'}
RULES = {
    'pageName': PAGES, 'previousPageName': PAGES | {None}, 'queryLength': ('int',0,100), 'resultCount': ('int',0,100000),
    'genre': {'전체','콘서트','뮤지컬','연극','페스티벌'}, 'clickTarget': {'poster','title','detail_button'},
    'trigger': {'date_change','time_change','booking_start'}, 'selectedDate': ('str',10,10),
    'initialRank': ('int',1,1000000000), 'estimatedWaitMs': ('number',0,86400000), 'elapsedMs': ('number',0,86400000),
    'reason': ('str',1,40), 'wrongCount': ('int',0,5), 'remainingAttempts': ('int',0,5), 'seatId': 'seat',
    'selectedCount': ('int',0,4), 'previousQuantity': ('int',1,4), 'quantity': ('int',1,4),
    'bookingId': ('str',1,50), 'seatType': {'reserved','general'}, 'totalAmount': ('int',0,1000000000),
    'durationMs': ('number',0,86400000), 'action': ('str',1,40), 'scenario': SCENARIOS,
}
DETAILS = {
    'page_enter': {'pageName','previousPageName'}, 'page_exit': {'pageName','previousPageName'},
    'search_change': {'queryLength','resultCount'}, 'genre_change': {'genre'}, 'show_select': {'clickTarget'},
    'schedule_select': {'trigger','selectedDate'}, 'seat_select': {'seatId','selectedCount'},
    'seat_cancel': {'seatId','selectedCount'}, 'quantity_change': {'previousQuantity','quantity'},
    'queue_register': {'initialRank','estimatedWaitMs'}, 'queue_admitted': {'elapsedMs'},
    'queue_cancel': {'reason','elapsedMs'}, 'connection_timeout': {'reason','elapsedMs'},
    'captcha_wrong': {'wrongCount','remainingAttempts'}, 'captcha_limit_reached': {'wrongCount','remainingAttempts'},
    'captcha_refresh': {'reason'}, 'booking_access_rejected': {'action'}, 'booking_not_open': {'action'},
    'booking_confirm_rejected': {'action'}, 'scenario_executed': {'scenario'},
    **{kind:{'bookingId','seatType','quantity','totalAmount','durationMs'} for kind in ('booking_confirm_request','booking_confirm_success','booking_confirm_fail','booking_confirm_replayed')},
}
OPTIONAL_DETAILS = {'booking_confirm_request','booking_confirm_fail','booking_confirm_rejected'}


class EventValidationError(ValueError):
    pass


def timestamp(value):
    try:
        if not isinstance(value, str) or len(value)>40:
            raise ValueError
        date = datetime.fromisoformat(value)
        if date.tzinfo is None or date.utcoffset().total_seconds()!=0:
            raise ValueError
        return date
    except ValueError:
        raise EventValidationError('timestamp must be UTC') from None


def validate_details(kind, details, require=False):
    if not isinstance(details, dict) or set(details)-DETAILS.get(kind,set()):
        raise EventValidationError('unknown details field')
    if require and kind not in OPTIONAL_DETAILS and DETAILS.get(kind,set())-set(details):
        raise EventValidationError('missing required details')
    for name,value in details.items():
        rule=RULES[name]
        if isinstance(rule,set):
            valid=isinstance(value,(str,type(None))) and value in rule
        elif rule=='seat':
            valid=isinstance(value,str) and re.fullmatch(r'[A-J](?:10|[1-9])',value)
        else:
            typ,low,high=rule
            valid=(type(value) is int and low<=value<=high) if typ=='int' else ((type(value) in (int,float) and low<=value<=high) if typ=='number' else (isinstance(value,str) and low<=len(value)<=high))
        if not valid:
            raise EventValidationError('invalid details type, range or enum')


def validate_event(event, require_details=False):
    if not isinstance(event,dict) or set(event)!=FIELDS:
        raise EventValidationError('invalid event fields')
    if type(event['schemaVersion']) is not int or event['schemaVersion']!=1:
        raise EventValidationError('unsupported schemaVersion')
    try:
        UUID(event['eventId'])
    except (ValueError,TypeError,AttributeError):
        raise EventValidationError('invalid eventId') from None
    kind=event['eventType']
    if not isinstance(kind,str) or kind not in CLIENT_EVENTS|SERVER_EVENTS:
        raise EventValidationError('invalid eventType')
    if event['source'] not in ('browser','server') or (event['source']=='browser' and kind not in CLIENT_EVENTS):
        raise EventValidationError('invalid source')
    timestamp(event['occurredAt']); timestamp(event['receivedAt'])
    for name in ('userId','pageInstanceId','pageViewId','bookingAttemptId','showId','scheduleId','errorCode'):
        value=event[name]
        if value is not None and (not isinstance(value,str) or not 1<=len(value)<=100):
            raise EventValidationError('invalid identifier')
    seq=event['requestSequence']
    if seq is not None and (type(seq) is not int or not 1<=seq<=2**53-1):
        raise EventValidationError('invalid requestSequence')
    if event['result'] not in ('success','failure','rejected') or type(event['isSimulation']) is not bool:
        raise EventValidationError('invalid result or simulation flag')
    scenario=event['scenarioName']
    if scenario is not None and (not isinstance(scenario,str) or scenario not in SCENARIOS or not event['isSimulation']):
        raise EventValidationError('invalid scenarioName')
    validate_details(kind,event['details'],require_details)
    try:
        payload=json.dumps(event,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    except (ValueError,TypeError):
        raise EventValidationError('invalid JSON') from None
    if len(payload)>16384:
        raise EventValidationError('event too large')
    return payload
