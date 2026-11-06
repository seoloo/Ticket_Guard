import base64
import json
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from django.test import SimpleTestCase,override_settings,Client
from django.http import HttpResponse,StreamingHttpResponse
from .events import publisher,build_capture,build_event,transport_records,KafkaEventPublisher
from .telemetry import sanitize_capture,body_snapshot
from .middleware import RequestTelemetryMiddleware
from django.urls import path

def capture_test_exception(request):
    raise RuntimeError('password=error-credential-sentinel')

urlpatterns=[path('__capture_test_error__/',capture_test_exception)]


@override_settings(EVENT_PUBLISHER='mock',DEMO_PASSWORD='demo-password')
class CaptureTests(SimpleTestCase):
    def setUp(self):
        publisher.receipts.clear();publisher.records.clear()
        self.client.get('/login/')

    def payload(self,**extra):
        return dict(eventId=str(uuid4()),eventType='future_observation',
            occurredAt=datetime.now(timezone.utc).isoformat(),pageInstanceId='tab',pageViewId=str(uuid4()),
            details={'arbitrary':{'array':list(range(90)),'text':'x'*20000}},**extra)

    def post(self,item,client=None):
        return (client or self.client).post('/api/capture/',json.dumps(item),content_type='application/json')

    def test_anonymous_extended_fields_and_no_silent_truncation(self):
        item=self.payload(extraField={'keep':True})
        result=self.post(item)
        self.assertEqual(result.status_code,200)
        event=publisher.receipts[item['eventId']]['event']
        self.assertEqual(event['schemaVersion'],2)
        self.assertEqual(event['source'],'browser')
        self.assertIsNone(event['userId'])
        self.assertEqual(len(event['details']['arbitrary']['text']),20000)
        self.assertEqual(len(event['details']['arbitrary']['array']),90)
        self.assertEqual(event['details']['observerExtensions']['extraField'],{'keep':True})
        self.assertEqual(self.post(item).json()['duplicate'],True)
        self.assertEqual(self.client.get('/api/capture/',{'eventId':item['eventId']}).json()['state'],'delivered')
        self.assertEqual(Client().get('/api/capture/',{'eventId':item['eventId']}).status_code,404)

    def test_redaction_audit_and_nonsecret_query_headers_preserved(self):
        item=self.payload()
        item['details']={'request':{'url':'/api/action/?q=music&q=live&token=credential-value#section',
            'headers':[{'name':'X-Custom','value':'keep'},{'name':'Authorization','value':'Bearer credential-value'}],
            'body':{'value':{'username':'user','password':'credential-value','newField':'keep'}}}}
        self.post(item)
        event=publisher.receipts[item['eventId']]['event']
        text=json.dumps(event)
        self.assertNotIn('credential-value',text)
        self.assertIn('q=music&q=live',text)
        self.assertEqual(event['details']['request']['headers'][0]['value'],'keep')
        self.assertTrue(event['capture']['redactions'])
        self.assertEqual(event['details']['request']['body']['value']['newField'],'keep')

    def test_receipt_survives_login_identity_change(self):
        item=self.payload();self.post(item)
        session=self.client.session;session['user']='new-user';session.save()
        self.client.cookies['sessionid']=session.session_key
        self.assertTrue(self.post(item).json()['duplicate'])

    def test_capture_csrf_and_explicit_body_rejection(self):
        client=Client(enforce_csrf_checks=True)
        client.get('/login/')
        self.assertEqual(self.post(self.payload(),client).status_code,403)
        token=client.cookies['csrftoken'].value
        item=self.payload()
        result=client.post('/api/capture/',json.dumps(item),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code,200)
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=100):
            result=self.post(self.payload())
            self.assertEqual(result.status_code,413)
            self.assertEqual(result.json()['errorCode'],'HTTP_BODY_LIMIT')

    def test_logical_duplicate_conflict_and_retry(self):
        item=self.payload()
        with patch.object(publisher,'_backend') as backend:
            backend.return_value.publish.side_effect=lambda event,cb:cb({'code':'TEMP','retryable':True},None)
            self.assertEqual(self.post(item).status_code,503)
            backend.return_value.publish.side_effect=lambda event,cb:cb(None,{'mock':True})
            self.assertEqual(self.post(item).json()['state'],'delivered')
        item['details']['arbitrary']['new']='changed'
        self.assertEqual(self.post(item).status_code,400)

    def test_server_full_bodies_and_query_and_header(self):
        response=self.client.post('/api/action/?q=music&q=live',json.dumps({'action':'heartbeat','password':'sensitive-sentinel','future':123}),
            content_type='application/json',HTTP_X_CUSTOM='kept')
        event=[e for e in publisher.records if e['eventType']=='server_request'][-1]
        d=event['details']
        self.assertEqual(d['request']['body']['value']['future'],123)
        self.assertEqual(d['request']['query'],[{'name':'q','value':'music'},{'name':'q','value':'live'}])
        self.assertIn({'name':'X-Custom','value':'kept'},d['request']['headers'])
        self.assertEqual(d['response']['status'],response.status_code)
        self.assertEqual(d['response']['body']['representation'],'json')
        self.assertNotIn('sensitive-sentinel',json.dumps(event))
        self.assertEqual(d['requestId'],response['X-Request-ID'])

    def test_collector_requests_not_recursively_observed(self):
        before=len(publisher.records);item=self.payload();self.post(item)
        self.client.get('/api/capture/',{'eventId':item['eventId']});self.client.get('/health/')
        self.assertEqual(len(publisher.records),before+1)

    def test_binary_empty_and_multipart_representations(self):
        binary=b'\x00\xffabc'
        snap=body_snapshot(binary,'application/octet-stream')
        self.assertEqual(base64.b64decode(snap['value']),binary)
        self.assertEqual(body_snapshot(b'')['state'],'empty')
        form=body_snapshot(b'q=a&q=b&password=sentinel','application/x-www-form-urlencoded')
        clean,audit=sanitize_capture(form)
        self.assertEqual(clean['value'][0:2],[{'name':'q','value':'a'},{'name':'q','value':'b'}])
        self.assertNotIn('sentinel',json.dumps(clean));self.assertTrue(audit['redactions'])
        raw=b'--test\r\nContent-Disposition: form-data; name="file"; filename="f.bin"\r\nContent-Type: application/octet-stream\r\n\r\n\x00abc\r\n--test--\r\n'
        snap=body_snapshot(raw,'multipart/form-data; boundary=test')
        self.assertEqual(snap['representation'],'multipart')
        self.assertEqual(base64.b64decode(snap['value'][0]['value']['value']),b'\x00abc')

    def test_chunks_reassemble_complete_unicode_record_and_stable_ids(self):
        event=build_capture(None,'future',{'text':'한글'*50000},{'anonymousId':'anonymous'})
        chunks=transport_records(event)
        self.assertGreater(len(chunks),1)
        self.assertTrue(all(len(c)<=16384 for c in chunks))
        rows=[json.loads(c) for c in chunks]
        reconstructed=json.loads(b''.join(base64.b64decode(r['details']['data']) for r in sorted(rows,key=lambda r:r['details']['index'])))
        self.assertEqual(reconstructed,event)
        self.assertEqual(chunks,transport_records(event))

    def test_kafka_logical_ack_waits_for_all_chunks(self):
        event=build_capture(None,'future',{'text':'x'*60000},{'anonymousId':'anonymous'})
        calls=[];receipts=[]
        backend=KafkaEventPublisher.__new__(KafkaEventPublisher)
        backend.producer=SimpleNamespace(produce=lambda *args,**kw:calls.append((args,kw)))
        with patch.dict('sys.modules',{'confluent_kafka':SimpleNamespace(KafkaError=object)}):
            backend.publish(event,lambda err,meta:receipts.append((err,meta)))
        for i,(args,kw) in enumerate(calls):
            self.assertEqual(kw['key'],b'anonymous')
            self.assertEqual(args[0],'ticketguard.events.v1')
            if i<len(calls)-1:self.assertEqual(receipts,[])
            kw['on_delivery'](None,SimpleNamespace(topic=lambda:'ticketguard.events.v1',partition=lambda:0,offset=lambda:i))
        self.assertEqual(len(receipts),1)
        self.assertEqual(len(receipts[0][1]['chunks']),len(calls))

    def test_capture_failure_does_not_change_business_result(self):
        with patch('web.middleware.publisher.publish',side_effect=BufferError('full')):
            response=self.client.get('/login/')
        self.assertEqual(response.status_code,200)

    def test_stream_is_not_eagerly_consumed(self):
        from django.test import RequestFactory
        request=RequestFactory().get('/stream/');request.session={}
        observed=[]
        def content():
            observed.append('read');yield b'hello';yield b'world'
        response=RequestTelemetryMiddleware(lambda req:StreamingHttpResponse(content(),content_type='text/plain'))(request)
        self.assertEqual(observed,[])
        self.assertEqual(b''.join(response.streaming_content),b'helloworld')
        event=[e for e in publisher.records if e['eventType']=='server_request'][-1]
        self.assertEqual(event['details']['response']['body']['value'],'helloworld')
        self.assertTrue(event['details']['response']['body']['streamComplete'])

    def test_server_multipart_credentials_not_hidden_in_binary(self):
        response=self.client.post('/api/action/?q=upload',{'password':'multipart-credential-sentinel','field':'keep'})
        event=[e for e in publisher.records if e['eventType']=='server_request'][-1]
        body=event['details']['request']['body']
        self.assertEqual(body['representation'],'multipart')
        self.assertNotIn('multipart-credential-sentinel',json.dumps(event))
        self.assertTrue(any(x['name']=='field' for x in body['value']))

    def test_json_text_copy_preserves_format_without_credentials(self):
        original=b'{ "extra" : [1, 2], "unicode" : "ok" }'
        snapshot=body_snapshot(original,'application/json')
        clean,audit=sanitize_capture(snapshot)
        self.assertEqual(clean['text'].encode(),original)
        self.assertEqual(audit['redactions'],[])

    def test_reassembly_rejects_corrupted_chunk(self):
        from .events import CaptureReassembler
        event=build_capture(None,'future',{'text':'x'*20000})
        rows=[json.loads(raw) for raw in transport_records(event)]
        rows[-1]['details']['data']=base64.b64encode(b'corrupt').decode()
        assembler=CaptureReassembler()
        with self.assertRaises(ValueError):
            for row in rows: assembler.feed(row)

    def test_unknown_and_large_server_business_fields_are_preserved(self):
        event=build_event('user','future_server_event',details={'field':'x'*25000,'all':list(range(100))})
        self.assertEqual(event['schemaVersion'],2)
        self.assertEqual(len(event['details']['field']),25000)
        self.assertGreater(len(transport_records(event)),1)

    def test_server_exception_details_and_response_are_observed(self):
        self.client.raise_request_exception=False
        with override_settings(ROOT_URLCONF=__name__,DEBUG=False):
            with self.assertLogs('django.request',level='ERROR'):
                response=self.client.get('/__capture_test_error__/')
        self.assertEqual(response.status_code,500)
        event=[e for e in publisher.records if e['eventType']=='server_request'][-1]
        self.assertEqual(event['details']['exception']['type'],'RuntimeError')
        self.assertIn('stack',event['details']['exception'])
        self.assertNotIn('error-credential-sentinel',json.dumps(event))
        self.assertEqual(event['result'],'failure')

    def test_partial_enqueue_reports_one_failure_after_remaining_callbacks(self):
        event=build_capture(None,'future',{'text':'x'*50000})
        calls=[];receipts=[];attempt=[0]
        def produce(*args,**kwargs):
            attempt[0]+=1
            if attempt[0]==2: raise BufferError('full')
            calls.append(kwargs)
        backend=KafkaEventPublisher.__new__(KafkaEventPublisher)
        backend.producer=SimpleNamespace(produce=produce)
        with patch.dict('sys.modules',{'confluent_kafka':SimpleNamespace(KafkaError=object)}):
            backend.publish(event,lambda err,meta:receipts.append((err,meta)))
        self.assertEqual(receipts,[])
        for kwargs in calls:
            kwargs['on_delivery'](None,SimpleNamespace(topic=lambda:'ticketguard.events.v1',partition=lambda:0,offset=lambda:7))
        self.assertEqual(len(receipts),1)
        self.assertEqual(receipts[0][0]['code'],'BUFFER_FULL')
        self.assertTrue(receipts[0][0]['retryable'])

    def test_unavailable_and_failed_body_statuses_are_auditable(self):
        event=build_capture(None,'future',{'request':{'body':{'state':'unavailable','reason':'opaque'}},
                                         'response':{'body':{'state':'failed','reason':'read_error'}}})
        self.assertEqual(event['capture']['status'],'partial')
        self.assertEqual(event['capture']['limitations'][0]['reason'],'opaque')
        self.assertEqual(event['capture']['failures'][0]['reason'],'read_error')

    def test_nonsecret_metric_names_are_not_masked_by_substring(self):
        data={'tokenCount':12,'passwordLength':8,'secretMetricCount':3,'token':'credential'}
        clean,audit=sanitize_capture(data)
        self.assertEqual(clean['tokenCount'],12)
        self.assertEqual(clean['passwordLength'],8)
        self.assertEqual(clean['secretMetricCount'],3)
        self.assertEqual(clean['token'],'[REDACTED]')
        self.assertEqual(len(audit['redactions']),1)
