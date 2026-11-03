"""Isolated Django fixtures + real Kafka. Does not mutate the live web process."""
import json
import time
from datetime import datetime,timezone
from unittest.mock import patch
from uuid import uuid4
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.test import Client,override_settings
from web.events import publisher,build_event
from web.event_schema import validate_event
from web.services import MockRepository


def wait_receipt(event_id,user,timeout=9):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=publisher.status(event_id,user)
        if result and result['state'] in ('delivered','failed'): return result
        time.sleep(.1)
    raise CommandError('Delivery callback deadline exceeded.')


class Command(BaseCommand):
    help='Verify real Kafka delivery. --outage expects broker initially stopped; restart it after printed marker.'
    def add_arguments(self,parser): parser.add_argument('--outage',action='store_true')

    def handle(self,*args,**options):
        if settings.EVENT_PUBLISHER!='kafka': raise CommandError('Set EVENT_PUBLISHER=kafka.')
        if options['outage']: return self.outage()
        from confluent_kafka import Consumer,TopicPartition
        topic=settings.KAFKA_EVENTS_TOPIC
        consumer=Consumer({'bootstrap.servers':settings.KAFKA_BOOTSTRAP_SERVERS,'group.id':'ticketguard-debug-verify-'+uuid4().hex,
                           'enable.auto.commit':False,'allow.auto.create.topics':False})
        try:
            metadata=consumer.list_topics(topic,timeout=10).topics[topic]
            positions=[]
            for number in metadata.partitions:
                part=TopicPartition(topic,number)
                _,end=consumer.get_watermark_offsets(part,timeout=5)
                positions.append(TopicPartition(topic,number,end))
            consumer.assign(positions)
            user='kafka-qa-'+uuid4().hex[:8]
            fixture=MockRepository()
            client=Client()
            def post(action,**data):
                return client.post('/api/action/',json.dumps(dict(action=action,pageId='qa-tab',pageViewId=str(uuid4()),**data)),content_type='application/json')
            with override_settings(ALLOWED_HOSTS=['testserver'],DEMO_USERNAME=user,DEMO_PASSWORD='isolated-fixture'),patch('web.views.repo',fixture):
                assert post('login',username=user,password='isolated-fixture').status_code==200
                assert post('start',showId='blue-hour').status_code==200
                a=fixture.attempts[user]
                a['entered']-=20
                assert post('heartbeat',attemptId=a['id']).status_code==200
                # Seed verified test state; no browser CAPTCHA is solved or bypassed on the live service.
                a['stage']='select'
                booking=post('confirm',attemptId=a['id'],sequence=1,seats=['E1','E2'],quantity=2)
                assert booking.status_code==200
                assert post('confirm',attemptId=a['id'],sequence=1,seats=['E1','E2'],quantity=2).status_code==200
                payload=dict(eventId=str(uuid4()),eventType='page_enter',occurredAt=datetime.now(timezone.utc).isoformat(),
                             pageInstanceId='qa-tab',pageViewId=str(uuid4()),showId=None,scheduleId=None,
                             details={'pageName':'history','previousPageName':'complete'})
                browser=client.post('/api/events/',json.dumps(payload),content_type='application/json')
                assert browser.status_code in (200,202)
                assert wait_receipt(payload['eventId'],user)['state']=='delivered'
                duplicate=client.post('/api/events/',json.dumps(payload),content_type='application/json')
                assert duplicate.json()['duplicate'] is True
                assert post('scenario',name='open_later',showId='blue-hour').status_code==200
                assert post('start',showId='blue-hour').status_code==409
            expected={e['eventId']:e for e in publisher.records if e['userId']==user}
            for event_id in expected:
                assert wait_receipt(event_id,user)['state']=='delivered'
            found={}
            deadline=time.monotonic()+12
            while time.monotonic()<deadline and len(found)<len(expected):
                message=consumer.poll(.3)
                if message is None or message.error(): continue
                event=json.loads(message.value())
                if event.get('eventId') not in expected: continue
                validate_event(event,require_details=True)
                key=event['bookingAttemptId'] or event['userId'] or event['eventId']
                assert message.key().decode()==key
                found[event['eventId']]=event
            assert set(found)==set(expected),'Expected events missing from Kafka'
            kinds=[e['eventType'] for e in found.values()]
            assert kinds.count('booking_confirm_success')==1
            assert kinds.count('booking_confirm_replayed')==1
            assert 'queue_admitted' in kinds and 'scenario_executed' in kinds and 'booking_not_open' in kinds
            assert next(e for e in found.values() if e['eventType']=='booking_not_open')['scenarioName']=='open_later'
            self.stdout.write(json.dumps({'result':'PASS','events':len(found),'types':sorted(kinds),
                'browserEventId':payload['eventId'],'browserReceipt':publisher.status(payload['eventId'],user),
                'bookingTotal':next(e['details']['totalAmount'] for e in found.values() if e['eventType']=='booking_confirm_success')},ensure_ascii=False))
        except AssertionError as exc:
            raise CommandError('Kafka integration assertion failed: '+str(exc)) from None
        finally: consumer.close()

    def outage(self):
        from confluent_kafka.admin import AdminClient
        user='outage-qa-'+uuid4().hex[:8]
        event=build_event(user,'login_success')
        receipt=publisher.publish(event)
        if receipt['state'] not in ('pending','failed'): raise CommandError('Expected stopped broker.')
        failed=wait_receipt(event['eventId'],user)
        if failed['state']!='failed' or not failed['retryable']: raise CommandError('Expected retryable delivery failure.')
        fixture=MockRepository()
        client=Client()
        started=time.monotonic()
        with override_settings(ALLOWED_HOSTS=['testserver'],DEMO_USERNAME=user,DEMO_PASSWORD='isolated-fixture'),patch('web.views.repo',fixture):
            def post(action,**data):
                return client.post('/api/action/',json.dumps(dict(action=action,pageId='qa-tab',**data)),content_type='application/json')
            if post('login',username=user,password='isolated-fixture').status_code!=200:
                raise CommandError('Login unavailable during outage.')
            if post('start',showId='blue-hour').status_code!=200:
                raise CommandError('Admission unavailable during outage.')
            a=fixture.attempts[user]
            a['stage']='select'
            response=post('confirm',attemptId=a['id'],sequence=1,seats=['C1'],quantity=1)
            if response.status_code!=200 or fixture.bookings[a['booking_id']]['total']!=55000:
                raise CommandError('Booking HTTP result changed during outage.')
            if time.monotonic()-started>2:
                raise CommandError('Web requests waited on unavailable Kafka.')
        self.stdout.write('FAILED_WAITING_FOR_RECOVERY '+event['eventId'])
        self.stdout.flush()
        deadline=time.monotonic()+100
        ready=False
        while time.monotonic()<deadline:
            try:
                metadata=AdminClient({'bootstrap.servers':settings.KAFKA_BOOTSTRAP_SERVERS,'socket.timeout.ms':1000}).list_topics(timeout=2)
                if settings.KAFKA_EVENTS_TOPIC in metadata.topics:
                    ready=True
                    break
            except Exception: pass
            time.sleep(1)
        if not ready: raise CommandError('Broker was not restarted within 100 seconds.')
        publisher.publish(event)
        delivered=wait_receipt(event['eventId'],user)
        fresh=build_event(user,'login_success')
        publisher.publish(fresh)
        if delivered['state']!='delivered' or wait_receipt(fresh['eventId'],user)['state']!='delivered':
            raise CommandError('Recovery did not deliver events.')
        self.stdout.write(json.dumps({'result':'PASS','outageBookingUnchanged':True,'sameEventIdRetry':event['eventId'],'receipt':delivered,'newEventDelivered':True}))
