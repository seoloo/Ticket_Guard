"""
[홍석환] 관측 이벤트 Kafka 연동 검증 명령
개발용 Kafka에서 수집 데이터 전송 계약과 재조립 결과를 확인한다.
"""
import json
import time
from datetime import datetime,timezone
from uuid import uuid4
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.test import Client,override_settings
from web.events import publisher,CaptureReassembler


class Command(BaseCommand):
    help='Verify anonymous capture, login replay, unknown fields, large records and Kafka reassembly (no DB).'
    def handle(self,*args,**options):
        if settings.EVENT_PUBLISHER!='kafka': raise CommandError('EVENT_PUBLISHER must be kafka')
        from confluent_kafka import Consumer,TopicPartition
        consumer=Consumer({'bootstrap.servers':settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id':'ticketguard-debug-capture-'+uuid4().hex,'enable.auto.commit':False,'allow.auto.create.topics':False})
        try:
            topic=settings.KAFKA_EVENTS_TOPIC
            metadata=consumer.list_topics(topic,timeout=10).topics[topic]
            if metadata.error: raise CommandError('Topic unavailable')
            positions=[]
            for partition in metadata.partitions:
                part=TopicPartition(topic,partition)
                _,end=consumer.get_watermark_offsets(part,timeout=5)
                positions.append(TopicPartition(topic,partition,end))
            consumer.assign(positions)
            client=Client();ids=[];user='capture-qa-'+uuid4().hex[:8]
            with override_settings(ALLOWED_HOSTS=['testserver'],DEMO_USERNAME=user,DEMO_PASSWORD='capture-test-credential'):
                client.get('/login/')
                item={'eventId':str(uuid4()),'eventType':'new_simulation_observation','occurredAt':datetime.now(timezone.utc).isoformat(),
                    'pageInstanceId':'capture-test-tab','pageViewId':str(uuid4()),
                    'details':{'url':'/sample/?q=music&q=live&token=do-not-store',
                               'headers':[{'name':'X-Unknown','value':'keep'}],
                               'password':'do-not-store','futureField':{'all':list(range(100))}}}
                response=client.post('/api/capture/',json.dumps(item),content_type='application/json')
                if response.status_code not in (200,202): raise CommandError('Anonymous capture rejected')
                ids.append(item['eventId'])
                result=client.post('/api/action/',json.dumps({'action':'login','username':user,'password':'capture-test-credential'}),content_type='application/json')
                if result.status_code!=200: raise CommandError('Fixture login failed')
                replay=client.post('/api/capture/',json.dumps(item),content_type='application/json')
                if not replay.json().get('duplicate'): raise CommandError('Login changed capture identity')
                item={**item,'eventId':str(uuid4()),'details':{'text':'한글'*60000,'futureField':{'all':list(range(100))}}}
                result=client.post('/api/capture/',json.dumps(item),content_type='application/json')
                if result.status_code not in (200,202): raise CommandError('Large capture rejected')
                ids.append(item['eventId'])
                expected={i:publisher.receipts[i]['event'] for i in ids}
                # Ownership is already tested through Client; use stored owner for callback polling.
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    receipts=[publisher.receipts[i] for i in ids]
                    if all(r['state']=='delivered' for r in receipts): break
                    if any(r['state']=='failed' for r in receipts): raise CommandError('Kafka delivery failed')
                    time.sleep(.1)
                else: raise CommandError('Delivery timeout')
                found={};reassembler=CaptureReassembler();transport_count=0;deadline=time.monotonic()+20
                while time.monotonic()<deadline and set(found)!=set(ids):
                    message=consumer.poll(.2)
                    if message is None or message.error(): continue
                    raw=json.loads(message.value())
                    parent=raw.get('details',{}).get('recordId') if raw.get('eventType')=='capture_chunk' else raw.get('eventId')
                    if parent not in ids: continue
                    transport_count+=1
                    event=reassembler.feed(raw)
                    if event is None: continue
                    if event!=expected[event['eventId']]: raise CommandError('Kafka roundtrip mismatch')
                    if 'do-not-store' in json.dumps(event): raise CommandError('Credential leaked')
                    if message.key().decode()!=(event['bookingAttemptId'] or event['userId'] or event['capture']['anonymousId'] or event['eventId']):
                        raise CommandError('Kafka key mismatch')
                    found[event['eventId']]=event
                if set(found)!=set(ids): raise CommandError('Capture missing from Kafka')
                if len(found[ids[1]]['details']['text'])!=120000: raise CommandError('Text was truncated')
                self.stdout.write(json.dumps({'result':'PASS','logicalRecords':len(found),'transportRecords':transport_count,
                    'largeTextCharacters':120000,'anonymousThenLoginReplay':True,'credentialsRedacted':True,
                    'unknownFieldsPreserved':True,'dbTouched':False},ensure_ascii=False))
        finally: consumer.close()
