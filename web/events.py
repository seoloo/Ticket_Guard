"""Asynchronous, bounded delivery. This is NOT a durable outbox."""
import atexit
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
from uuid import uuid4
from django.conf import settings
from .event_schema import CLIENT_EVENTS, EventValidationError, validate_event

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
    def publish(self,event,callback): callback(None,{'mock':True})
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
        def delivered(error,message):
            if error:
                callback({'code':str(error.code()),'retryable':error.retriable() or error.code() in
                          (KafkaError._MSG_TIMED_OUT,KafkaError._TRANSPORT,KafkaError._ALL_BROKERS_DOWN)},None)
            else:
                callback(None,{'topic':message.topic(),'partition':message.partition(),'offset':message.offset()})
        key = event['bookingAttemptId'] or event['userId'] or event['eventId']
        self.producer.produce(settings.KAFKA_EVENTS_TOPIC,key=key.encode(),value=validate_event(event),on_delivery=delivered)

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

    def status(self,event_id,user):
        with self.lock:
            self._prune()
            record = self.receipts.get(event_id)
            return self.public(record) if record and record['event']['userId']==user else None

    def publish(self,event):
        validate_event(event,require_details=True)
        excluded={'receivedAt','isSimulation','scenarioName'}
        if event['source']=='browser': excluded.add('bookingAttemptId')
        stable = {k:v for k,v in event.items() if k not in excluded}
        fingerprint = hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            self._prune()
            record = self.receipts.get(event['eventId'])
            if record:
                if record['fingerprint']!=fingerprint: raise EventValidationError('eventId payload conflict')
                if record['state']!='failed' or not record['retryable'] or record['attempts']>=settings.EVENT_MAX_ATTEMPTS:
                    return dict(self.public(record),duplicate=True)
                event = record['event']
            else:
                self._prune(make_room=True)
                if len(self.receipts)>=settings.EVENT_RECEIPT_MAX:
                    self.counters['capacity_rejected']+=1
                    raise BufferError('receipt capacity reached')
                record = dict(event=copy.deepcopy(event),fingerprint=fingerprint,state='received',attempts=0,
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
