import copy
import json
from datetime import datetime,timezone
from unittest.mock import patch
from uuid import uuid4
from time import monotonic
from django.conf import settings
from django.test import SimpleTestCase,override_settings
from .events import EventDispatcher,build_event,publisher
from .event_schema import validate_event,EventValidationError
from .services import MockRepository


@override_settings(EVENT_PUBLISHER='mock')
class DeliveryTests(SimpleTestCase):
    def test_mock_delivered_and_same_id_not_published_twice(self):
        dispatcher=EventDispatcher()
        event=build_event('one','login_success')
        self.assertEqual(dispatcher.publish(event)['state'],'delivered')
        self.assertTrue(dispatcher.publish(event)['duplicate'])
        self.assertEqual(len(dispatcher.records),1)

    def test_pending_is_not_delivered_and_failure_allows_retry(self):
        dispatcher=EventDispatcher()
        callbacks=[]
        class Backend:
            def publish(self,event,callback): callbacks.append(callback)
        with patch.object(dispatcher,'_backend',return_value=Backend()):
            event=build_event('one','login_success')
            self.assertEqual(dispatcher.publish(event)['state'],'pending')
            self.assertTrue(dispatcher.publish(event)['duplicate'])
            self.assertEqual(len(callbacks),1)
            callbacks[0]({'code':'TIMEOUT','retryable':True},None)
            self.assertEqual(dispatcher.status(event['eventId'],'one')['state'],'failed')
            self.assertEqual(dispatcher.publish(event)['attempts'],2)
            callbacks[1](None,{'topic':'test','partition':0,'offset':7})
            self.assertEqual(dispatcher.status(event['eventId'],'one')['state'],'delivered')
            self.assertIsNone(dispatcher.status(event['eventId'],'another'))

    def test_same_id_different_payload_rejected(self):
        dispatcher=EventDispatcher()
        event=build_event('one','login_success')
        dispatcher.publish(event)
        event['eventType']='login_fail'
        with self.assertRaises(EventValidationError): dispatcher.publish(event)

    def test_schema_disallows_secrets_unknown_fields_and_server_forgery(self):
        event=build_event('one','login_success')
        for bad in ({**event,'password':'secret'}, {**event,'details':{'token':'secret'}}, {**event,'source':'browser'}):
            with self.assertRaises(EventValidationError): validate_event(bad)
        event['requestSequence']=True
        with self.assertRaises(EventValidationError): validate_event(event)

    def test_receipt_capacity_and_ttl(self):
        dispatcher=EventDispatcher()
        class Pending:
            def publish(self,event,callback): pass
        with override_settings(EVENT_RECEIPT_MAX=1),patch.object(dispatcher,'_backend',return_value=Pending()):
            dispatcher.publish(build_event('one','login_success'))
            with self.assertRaises(BufferError): dispatcher.publish(build_event('one','login_success'))
        record=next(iter(dispatcher.receipts.values()))
        

        record.update(
            state='failed',
            updated=monotonic() - settings.EVENT_RECEIPT_TTL_SECONDS - 1,
        )
        self.assertIsNone(dispatcher.status(record['event']['eventId'],'one'))

    def test_terminal_failure_does_not_retry(self):
        dispatcher=EventDispatcher()
        class Permanent:
            def publish(self,event,callback): callback({'code':'AUTH','retryable':False},None)
        with patch.object(dispatcher,'_backend',return_value=Permanent()):
            event=build_event('one','login_success')
            dispatcher.publish(event)
            self.assertEqual(dispatcher.publish(event)['attempts'],1)


@override_settings(EVENT_PUBLISHER='mock',DEMO_USERNAME='ticketguard',DEMO_PASSWORD='demo-password',SHOW_SCENARIOS=True)
class EventHttpTests(SimpleTestCase):
    def setUp(self):
        self.repo=MockRepository()
        self.patcher=patch('web.views.repo',self.repo)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client.post('/api/action/',json.dumps({'action':'login','username':'ticketguard','password':'demo-password'}),content_type='application/json')

    def payload(self):
        return dict(eventId=str(uuid4()),eventType='page_enter',occurredAt=datetime.now(timezone.utc).isoformat(),
                    pageInstanceId='tab-one',pageViewId=str(uuid4()),showId=None,scheduleId=None,
                    details={'pageName':'shows','previousPageName':None})

    def send(self,event): return self.client.post('/api/events/',json.dumps(event),content_type='application/json')

    def test_receipt_owner_and_sensitive_fields(self):
        event=self.payload()
        result=self.send(event)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['state'],'delivered')
        self.assertNotIn('metadata',result.json())
        self.assertEqual(self.client.get('/api/events/',{'eventId':event['eventId']}).json()['state'],'delivered')
        self.assertEqual(self.send({**event,'isSimulation':True}).status_code,400)
        self.assertEqual(self.send({**event,'eventType':'booking_confirm_success'}).status_code,400)

    def test_failed_publish_can_be_retried_same_event_id(self):
        event=self.payload()
        with patch.object(publisher,'_backend') as backend:
            backend.return_value.publish.side_effect=lambda event,callback: callback({'code':'TIMEOUT','retryable':True},None)
            self.assertEqual(self.send(event).status_code,503)
            backend.return_value.publish.side_effect=lambda event,callback: callback(None,{'mock':True})
            response=self.send(event)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['attempts'],2)

    def test_scenario_is_server_owned_and_rejections_are_logged(self):
        request=dict(action='scenario',name='open_later',showId='blue-hour',pageId='tab-one')
        self.client.post('/api/action/',json.dumps(request),content_type='application/json')
        request.update(action='start')
        self.assertEqual(self.client.post('/api/action/',json.dumps(request),content_type='application/json').status_code,409)
        logs=[event for event in publisher.records if event['eventType']=='booking_not_open']
        self.assertTrue(logs[-1]['isSimulation'])
        self.assertEqual(logs[-1]['scenarioName'],'open_later')

    def test_detail_values_types_and_no_search_text(self):
        event=self.payload()
        event.update(eventType='search_change',details={'queryLength':5,'resultCount':0})
        self.assertEqual(self.send(event).status_code,200)
        for details in ({'queryLength':5,'resultCount':0,'query':'secret'}, {'queryLength':-1,'resultCount':0}):
            event.update(eventId=str(uuid4()),details=details)
            self.assertEqual(self.send(event).status_code,400)
