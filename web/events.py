"""
[홍석환] 이벤트 생성과 Kafka 비동기 발행
전송 상태·재시도·중복·청크 분할과 재조립을 관리한다.
메모리 기반 발행 상태는 영속 송신 보관함을 대신하지 않는다.
"""
import atexit
import base64
import math
import copy
import hashlib
import json
import logging
import os
import threading
import time
from collections import Counter, OrderedDict, deque
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4, uuid5, NAMESPACE_URL
from django.conf import settings
from .event_schema import CLIENT_EVENTS, SERVER_EVENTS, EventValidationError, validate_event

logger = logging.getLogger('ticketguard.events')
request_context = ContextVar('event_context', default={})


def event_request_context(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        data = {}
        try:
            if request.method == 'POST' and len(request.body) <= 16384:
                parsed = json.loads(request.body)
                if isinstance(parsed, dict): data = parsed
            elif request.method == 'GET': data = request.GET
        except (ValueError, UnicodeDecodeError):
            pass
        context = {dest:data[src] for src,dest in (('pageId','pageInstanceId'),('pageViewId','pageViewId'))
                   if isinstance(data.get(src),str) and 1<=len(data[src])<=100}
        token = request_context.set(context)
        try: return view(request,*args,**kwargs)
        finally: request_context.reset(token)
    return wrapped


class MockEventPublisher:
    def publish(self,event,callback): callback(None,{'mock':True,'chunks':len(transport_records(event))})
    def close(self): pass


class KafkaEventPublisher:
    def __init__(self):
        from confluent_kafka import Producer
        self.pid = os.getpid()
        self.stop = threading.Event()
        self.producer = Producer({'bootstrap.servers':settings.KAFKA_BOOTSTRAP_SERVERS,
            'client.id':settings.KAFKA_CLIENT_ID+'-'+str(self.pid),'enable.idempotence':True,
            'acks':'all','retries':3,'max.in.flight.requests.per.connection':5,
            'message.timeout.ms':settings.KAFKA_DELIVERY_TIMEOUT_MS,'request.timeout.ms':2000,
            'socket.timeout.ms':3000,'retry.backoff.ms':250,'linger.ms':10,
            'queue.buffering.max.messages':2000,'queue.buffering.max.kbytes':8192,
            'allow.auto.create.topics':False,'log_level':3,
            'error_cb':lambda err:logger.warning('kafka_transport code=%s',err.code())})
        self.thread = threading.Thread(target=self._poll,name='kafka-poll',daemon=True)
        self.thread.start()

    def _poll(self):
        while not self.stop.is_set():
            try: self.producer.poll(.1)
            except Exception:
                logger.error('kafka_poll_failed')
                self.stop.wait(.2)

    def publish(self,event,callback):
        from confluent_kafka import KafkaError
        records=transport_records(event)
        pending=len(records)
        results=[]
        errors=[]
        lock=threading.RLock()
        def delivered(error,message):
            nonlocal pending
            with lock:
                if error:
                    errors.append({'code':str(error.code()),'retryable':error.retriable() or error.code() in
                        (KafkaError._MSG_TIMED_OUT,KafkaError._TRANSPORT,KafkaError._ALL_BROKERS_DOWN)})
                else:
                    results.append({'topic':message.topic(),'partition':message.partition(),'offset':message.offset()})
                pending-=1
                if pending==0:
                    if errors: callback({'code':errors[0]['code'],'retryable':all(e['retryable'] for e in errors)},None)
                    else: callback(None,results[0] if len(records)==1 else {'chunks':results,'recordId':event['eventId']})
        key=event['bookingAttemptId'] or event['userId'] or event.get('capture',{}).get('anonymousId') or event['eventId']
        for record in records:
            try:
                self.producer.produce(settings.KAFKA_EVENTS_TOPIC,key=key.encode(),value=record,on_delivery=delivered)
            except Exception as exc:
                # Partial enqueue can still yield messages. Report one logical failure;
                # deterministic chunk IDs let downstream remove retry duplicates.
                with lock:
                    errors.append({'code':'BUFFER_FULL' if isinstance(exc,BufferError) else type(exc).__name__,
                                   'retryable':isinstance(exc,BufferError)})
                    pending-=1
                    if pending==0: callback(errors[0],None)

    def close(self):
        if os.getpid()!=self.pid: return
        if self.stop.is_set(): return
        self.stop.set()
        self.thread.join(timeout=1)
        pending = self.producer.flush(3)
        if pending: logger.error('kafka_shutdown_pending count=%d',pending)


class EventDispatcher:
    def __init__(self):
        self.lock = threading.RLock()
        self.records = deque(maxlen=1000)
        self.receipts = OrderedDict()
        self.counters = Counter()
        self.failed = 0
        self.adapter = None
        self.mode = None
        self.pid = os.getpid()

    def after_fork(self):
        self.lock = threading.RLock()
        self.adapter,self.mode,self.pid = None,None,os.getpid()
        self.receipts = OrderedDict()
        self.records = deque(maxlen=1000)
        self.counters = Counter()
        self.failed = 0

    def _backend(self):
        if self.pid!=os.getpid(): self.after_fork()
        if self.adapter is None or self.mode!=settings.EVENT_PUBLISHER:
            if self.adapter: self.adapter.close()
            self.mode = settings.EVENT_PUBLISHER
            if self.mode not in ('mock','kafka'): raise ValueError('invalid publisher mode')
            self.adapter = KafkaEventPublisher() if self.mode=='kafka' else MockEventPublisher()
        return self.adapter

    def _prune(self,make_room=False):
        now = time.monotonic()
        for key,record in list(self.receipts.items()):
            if record['state'] in ('delivered','failed') and now-record['updated']>settings.EVENT_RECEIPT_TTL_SECONDS:
                del self.receipts[key]
        if make_room and len(self.receipts)>=settings.EVENT_RECEIPT_MAX:
            terminal = next((k for k,r in self.receipts.items() if r['state'] in ('delivered','failed')),None)
            if terminal: del self.receipts[terminal]

    @staticmethod
    def public(record):
        result={k:record[k] for k in ('state','attempts','retryable','errorCode','metadata')}
        result['retryable']=result['retryable'] and record['attempts']<settings.EVENT_MAX_ATTEMPTS
        return result

    def status(self,event_id,user,owner=None):
        with self.lock:
            self._prune()
            record = self.receipts.get(event_id)
            if not record: return None
            allowed = record.get('owner') == owner if owner is not None else record.get('owner') is None and record['event']['userId']==user
            return self.public(record) if allowed else None

    def publish(self,event,owner=None):
        validate_event(event,require_details=True)
        excluded={'receivedAt','isSimulation','scenarioName'}
        if event['source']=='browser':
            excluded.add('bookingAttemptId')
            if event['schemaVersion']==2: excluded.add('userId')
        stable = {k:v for k,v in event.items() if k not in excluded}
        fingerprint = hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            self._prune()
            record = self.receipts.get(event['eventId'])
            if record:
                if record.get('owner') != owner: raise EventValidationError('event owner conflict')
                if record['fingerprint']!=fingerprint: raise EventValidationError('eventId payload conflict')
                if record['state']!='failed' or not record['retryable'] or record['attempts']>=settings.EVENT_MAX_ATTEMPTS:
                    return dict(self.public(record),duplicate=True)
                event = record['event']
            else:
                self._prune(make_room=True)
                if len(self.receipts)>=settings.EVENT_RECEIPT_MAX:
                    self.counters['capacity_rejected']+=1
                    raise BufferError('receipt capacity reached')
                record = dict(event=copy.deepcopy(event),owner=owner,fingerprint=fingerprint,state='received',attempts=0,
                              retryable=True,errorCode=None,metadata=None,updated=time.monotonic())
                self.receipts[event['eventId']] = record
                self.records.append(copy.deepcopy(event))
                self.counters['received']+=1
            record.update(state='pending',attempts=record['attempts']+1,errorCode=None,updated=time.monotonic())
            self.counters['enqueued_attempts']+=1
            def callback(error,metadata):
                with self.lock:
                    record.update(state='failed' if error else 'delivered',retryable=bool(error and error['retryable']),
                                  errorCode=error['code'] if error else None,metadata=metadata,updated=time.monotonic())
                    self.counters[record['state']]+=1
                    if error:
                        self.failed+=1
                        logger.error('event_delivery_failed eventId=%s code=%s retryable=%s',event['eventId'],error['code'],error['retryable'])
            try: self._backend().publish(event,callback)
            except BufferError: callback({'code':'BUFFER_FULL','retryable':True},None)
            except Exception as exc: callback({'code':type(exc).__name__,'retryable':False},None)
            return dict(self.public(record),duplicate=False)

    def for_user(self,user):
        with self.lock:
            return [dict(e,delivery=self.public(self.receipts[e['eventId']]) if e['eventId'] in self.receipts else None)
                    for e in self.records if e['userId']==user][-100:]

    def metrics(self):
        with self.lock:
            return dict(mode=settings.EVENT_PUBLISHER,totalFailures=self.failed,counters=dict(self.counters),
                        states=dict(Counter(r['state'] for r in self.receipts.values())),receiptCount=len(self.receipts))

    def close(self):
        if self.adapter: self.adapter.close()


publisher = EventDispatcher()
atexit.register(publisher.close)
if hasattr(os,'register_at_fork'): os.register_at_fork(after_in_child=publisher.after_fork)


def build_event(user,event_type,attempt=None,**fields):
    now = datetime.now(timezone.utc).isoformat()
    event = dict(schemaVersion=1,eventId=str(uuid4()),eventType=event_type,occurredAt=now,receivedAt=now,userId=user,
                 bookingAttemptId=None,pageInstanceId=None,pageViewId=None,showId=None,scheduleId=None,requestSequence=None,
                 result='success',errorCode=None,source='server',isSimulation=False,scenarioName=None,details={})
    event.update(request_context.get())
    if attempt:
        event.update(bookingAttemptId=attempt['id'],pageInstanceId=attempt['page_id'],
                     pageViewId=request_context.get().get('pageViewId') or attempt.get('page_view_id'),
                     showId=attempt['show_id'],scheduleId=attempt['show_id']+'-evening',
                     isSimulation=bool(attempt.get('scenario')),scenarioName=attempt.get('scenario'))
    event.update(fields)
    if event.get('schemaVersion')==1:
        from .telemetry import sanitize_capture
        cleaned,audit=sanitize_capture(event['details'])
        event['details']=cleaned
        if audit['redactions'] or event_type not in CLIENT_EVENTS|SERVER_EVENTS or len(json.dumps(event,ensure_ascii=False,allow_nan=False).encode('utf-8'))>16384:
            event.update(schemaVersion=2,capture={**audit,'collectorVersion':'2.0','policyVersion':'simulation-raw-1'})
    validate_event(event,require_details=True)
    return event


def emit(user,event_type,attempt=None,**fields):
    try:
        event = build_event(user,event_type,attempt,**fields)
        publisher.publish(event)
        return event
    except Exception as exc:
        publisher.failed+=1
        logger.error('event_emit_failed eventType=%s errorClass=%s',event_type,type(exc).__name__)
        return None


def build_capture(user,kind,details,context=None,event_id=None,occurred_at=None,source='server',client_capture=None,known=()):
    from .telemetry import sanitize_capture
    context=context or {}
    cleaned,audit=sanitize_capture(details,known)
    audit['collectorVersion']='2.0'
    audit['policyVersion']='simulation-raw-1'
    audit['anonymousId']=context.get('anonymousId')
    # Do not trust browser claims as server verification; retain them as provenance.
    if client_capture:
        audit['observer']=sanitize_capture(client_capture,known)[0]
        if client_capture.get('redactions') and audit['status']=='complete': audit['status']='redacted'
    fields={k:context[k] for k in ('pageInstanceId','pageViewId','bookingAttemptId','showId','scheduleId') if k in context}
    if event_id: fields['eventId']=event_id
    if occurred_at: fields['occurredAt']=occurred_at
    status=cleaned.get('response',{}).get('status') if isinstance(cleaned.get('response'),dict) else None
    result='failure' if isinstance(status,int) and status>=400 else 'success'
    return build_event(user,kind,source=source,schemaVersion=2,capture=audit,details=cleaned,result=result,**fields)


def transport_records(event):
    """Keep the complete sanitized event; split it, never truncate it."""
    raw=validate_event(event)
    wire_limit=getattr(settings,'CAPTURE_KAFKA_RECORD_BYTES',16384)
    if len(raw)<=wire_limit: return [raw]
    if event['schemaVersion']!=2: raise EventValidationError('v1 event too large')
    chunk_size=wire_limit//2
    if chunk_size<128: raise EventValidationError('transport limit too small')
    total=math.ceil(len(raw)/chunk_size)
    records=[]
    for index in range(total):
        item=dict(event)
        item.update(eventId=str(uuid5(NAMESPACE_URL,event['eventId']+':'+str(index))),eventType='capture_chunk',
                    details={'recordId':event['eventId'],'index':index,'count':total,'encoding':'base64-json-utf8',
                             'totalBytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(raw[index*chunk_size:(index+1)*chunk_size]).decode()},
                    capture={'status':'transport_chunk','anonymousId':event['capture'].get('anonymousId')})
        encoded=validate_event(item)
        if len(encoded)>wire_limit: raise EventValidationError('chunk envelope exceeds transport limit')
        records.append(encoded)
    return records


class CaptureReassembler:
    """Diagnostic helper; raw consumers may store chunks as-is instead."""
    def __init__(self): self.pending={}
    def feed(self,event):
        if event.get('eventType')!='capture_chunk': return event
        part=event['details'];record_id=part['recordId']
        if type(part['index']) is not int or type(part['count']) is not int or not 0<=part['index']<part['count']:
            raise ValueError('invalid chunk position')
        state=self.pending.setdefault(record_id,{'count':part['count'],'sha256':part['sha256'],'parts':{}})
        if state['count']!=part['count'] or state['sha256']!=part['sha256']: raise ValueError('conflicting chunk metadata')
        data=base64.b64decode(part['data'],validate=True)
        prior=state['parts'].get(part['index'])
        if prior is not None and prior!=data: raise ValueError('conflicting chunk data')
        state['parts'][part['index']]=data
        if len(state['parts'])<state['count']: return None
        raw=b''.join(state['parts'][i] for i in range(state['count']))
        if len(raw)!=part['totalBytes'] or hashlib.sha256(raw).hexdigest()!=state['sha256']: raise ValueError('chunk integrity failed')
        result=json.loads(raw);validate_event(result)
        if result['eventId']!=record_id: raise ValueError('record ID mismatch')
        del self.pending[record_id]
        return result
