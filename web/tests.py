import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4
from django.test import SimpleTestCase, Client, override_settings
from . import services
from .services import MockRepository, FlowError
from .events import publisher


@override_settings(EVENT_PUBLISHER='mock')
class BookingTests(SimpleTestCase):
    def setUp(self):
        self.repo = MockRepository()

    def admitted(self, user='one', show='blue-hour', page='tab-one'):
        a = self.repo.start(user, show, page)
        a['entered'] -= 20
        self.repo.tick(user, page, a['id'])
        answer = self.repo.challenge(user, page, a['id'])
        self.repo.verify(user, page, a['id'], answer)
        return a

    def confirm(self, a, user='one', seats=None, qty=1, seq=1):
        return self.repo.confirm(user, a['page_id'], a['id'], seq, seats or ['E5', 'E6'], qty)

    def test_reserved_success_and_idempotent_retry(self):
        a = self.admitted()
        b = self.confirm(a)
        retry = self.confirm(a, seats=['F1'], seq=2)
        self.assertEqual(b['id'], retry['id'])
        self.assertEqual(b['total'], 110000)
        self.assertEqual(len(self.repo.bookings), 1)

    def test_general_success_and_server_price(self):
        a = self.admitted(show='open-air')
        b = self.confirm(a, qty=2)
        self.assertEqual((b['quantity'], b['total'], self.repo.remaining), (2, 70000, 26))

    def test_five_wrong_answers_and_reentry_reset(self):
        a = self.repo.start('one', 'blue-hour', 'tab-one')
        a['entered'] -= 20
        self.repo.tick('one', 'tab-one', a['id'])
        self.repo.challenge('one', 'tab-one', a['id'])
        for i in range(5):
            with self.assertRaises(FlowError) as caught:
                self.repo.verify('one', 'tab-one', a['id'], 'WRONG')
            self.assertEqual(caught.exception.code, 'CAPTCHA_LIMIT' if i == 4 else 'CAPTCHA_WRONG')
        new = self.repo.start('one', 'blue-hour', 'tab-one')
        self.assertEqual(new['wrong'], 0)
        self.assertGreater(new['rank'], a['rank'])

    def test_captcha_refresh_keeps_wrong_count(self):
        a = self.repo.start('one', 'blue-hour', 'tab-one')
        a['entered'] -= 20
        self.repo.tick('one', 'tab-one', a['id'])
        a['wrong'] = 3
        self.repo.challenge('one', 'tab-one', a['id'])
        self.assertEqual(a['wrong'], 3)

    def test_only_owner_tab_can_mutate(self):
        a = self.admitted()
        with self.assertRaises(FlowError):
            self.repo.start('one', 'blue-hour', 'other-tab')
        with self.assertRaises(FlowError):
            self.repo.cancel('one', 'other-tab', a['id'])

    def test_expiry_and_cancel_reentry(self):
        a = self.admitted()
        a['heartbeat'] -= 61
        with self.assertRaises(FlowError):
            self.confirm(a)
        b = self.repo.start('one', 'blue-hour', 'tab-one')
        self.repo.cancel('one', 'tab-one', b['id'])
        c = self.repo.start('one', 'blue-hour', 'tab-one')
        self.assertGreater(c['rank'], b['rank'])

    def test_inventory_conflict_and_stale_sequence(self):
        a = self.admitted()
        self.repo.sold.add('E6')
        with self.assertRaises(FlowError) as error:
            self.confirm(a, seq=2)
        self.assertEqual(error.exception.code, 'SEAT_SOLD')
        with self.assertRaises(FlowError) as error:
            self.confirm(a, seats=['F1'], seq=1)
        self.assertEqual(error.exception.code, 'STALE_REQUEST')
        self.assertEqual(len(self.repo.bookings), 0)

    def test_general_shortage(self):
        a = self.admitted(show='open-air')
        self.repo.remaining = 1
        with self.assertRaises(FlowError) as error:
            self.confirm(a, qty=2)
        self.assertEqual(error.exception.code, 'INSUFFICIENT_STOCK')
        self.assertEqual(self.repo.remaining, 1)

    def test_selection_limits_and_unverified_access(self):
        a = self.repo.start('one', 'blue-hour', 'tab-one')
        with self.assertRaises(FlowError):
            self.confirm(a)
        a = self.admitted()
        for seq, seats in enumerate([['E1']*2, ['E1','E2','E3','E4','E5'], ['Z99']], start=1):
            with self.assertRaises(FlowError):
                self.confirm(a, seats=seats, seq=seq)
        self.assertEqual(len(self.repo.bookings), 0)

    def test_atomic_competing_users(self):
        one = self.admitted()
        two = self.admitted(user='two', page='tab-two')
        def buy(args):
            a, user = args
            try:
                return self.confirm(a, user=user)['id']
            except FlowError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, [(one, 'one'), (two, 'two')]))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.repo.bookings), 1)

    def test_no_open_before_server_time(self):
        self.repo.opens['one', 'blue-hour'] = time.time() + 60
        with self.assertRaises(FlowError) as error:
            self.repo.start('one', 'blue-hour', 'tab-one')
        self.assertEqual(error.exception.code, 'NOT_OPEN')

    def test_event_failure_does_not_undo_booking(self):
        a = self.admitted()
        with patch.object(publisher, 'publish', side_effect=RuntimeError('offline')):
            b = self.confirm(a)
        self.assertIn(b['id'], self.repo.bookings)


@override_settings(EVENT_PUBLISHER='mock',DEMO_USERNAME='ticketguard', DEMO_SECOND_USERNAME='guest', DEMO_PASSWORD='demo-password', SHOW_SCENARIOS=True)
class WebTests(SimpleTestCase):
    def setUp(self):
        self.repo = MockRepository()
        self.patcher = patch('web.views.repo', self.repo)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        publisher.records.clear()

    def post(self, action, **data):
        return self.client.post('/api/action/', data=json.dumps(dict(action=action, **data)), content_type='application/json')

    def login(self):
        self.assertEqual(self.post('login', username='ticketguard', password='demo-password').status_code, 200)

    def ready(self, show='blue-hour'):
        self.login()
        a = self.repo.start('ticketguard', show, 'tab-one')
        a['entered'] -= 20
        self.repo.tick('ticketguard', 'tab-one', a['id'])
        answer = self.repo.challenge('ticketguard', 'tab-one', a['id'])
        self.repo.verify('ticketguard', 'tab-one', a['id'], answer)
        return a

    def test_login_fail_anonymous_and_csrf(self):
        self.assertRedirects(self.client.get('/'), '/login/', fetch_redirect_response=False)
        self.assertEqual(self.post('login', username='ticketguard', password='bad').status_code, 401)
        self.assertEqual(self.post('start', showId='blue-hour', pageId='tab-one').status_code, 401)
        secure_client = Client(enforce_csrf_checks=True)
        response = secure_client.post('/api/action/', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_templates_search_and_direct_step_access(self):
        self.login()
        for path in ['/', '/detail/blue-hour/', '/detail/open-air/', '/history/']:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertContains(self.client.get('/?q=nothing-found'), '검색 결과가 없어요')
        self.assertEqual(self.client.get('/select/').status_code, 302)
        self.assertEqual(self.client.get('/unknown/').status_code, 404)

    def test_queue_captcha_and_png_secrecy(self):
        self.login()
        a = self.repo.start('ticketguard', 'blue-hour', 'tab-one')
        self.assertContains(self.client.get('/queue/'), '조금만 기다려 주세요')
        a['entered'] -= 20
        self.repo.tick('ticketguard', 'tab-one', a['id'])
        response = self.client.get('/captcha.png', {'pageId': 'tab-one', 'attemptId': a['id']})
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response.content[:8], b'\x89PNG\r\n\x1a\n')
        self.assertNotContains(self.client.get('/captcha/'), a['captcha'])
        self.assertEqual(self.client.get('/captcha.png', {'pageId': 'other', 'attemptId': a['id']}).status_code, 409)

    def test_reserved_100_seats_and_history_isolation(self):
        a = self.ready()
        response = self.client.get('/select/')
        self.assertEqual(response.content.count(b'data-seat='), 100)
        result = self.post('confirm', pageId='tab-one', attemptId=a['id'], sequence=1, seats=['E5','E6'], quantity=4, price=1)
        self.assertEqual(result.status_code, 200)
        url = result.json()['redirect']
        self.assertContains(self.client.get(url), '110000')
        self.assertContains(self.client.get('/history/'), '블루 아워 라이브')
        self.post('logout')
        self.post('login', username='guest', password='demo-password')
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertContains(self.client.get('/history/'), '아직 예매한 공연이 없어요')

    def test_general_template(self):
        self.ready('open-air')
        self.assertContains(self.client.get('/select/'), '관람 인원')

    def test_client_event_validation_dedup_and_server_identity(self):
        self.login()
        data = dict(eventType='page_enter', eventId=str(uuid4()), occurredAt='2026-01-01')
        def post():
            return self.client.post('/api/events/', json.dumps(data), content_type='application/json')
        self.assertEqual(post().status_code, 400)
        from datetime import datetime, timezone
        data.update(occurredAt=datetime.now(timezone.utc).isoformat(), pageInstanceId='tab-one', pageViewId=str(uuid4()),details={'pageName':'shows','previousPageName':None},userId='forged')
        self.assertEqual(post().status_code,400)
        data.pop('userId')
        self.assertEqual(post().status_code, 200)
        self.assertTrue(post().json()['duplicate'])
        last = publisher.records[-1]
        self.assertEqual(last['userId'], 'ticketguard')
        self.assertEqual(last['source'], 'browser')
        data['eventType'] = 'booking_confirm_success'
        self.assertEqual(post().status_code, 400)

    def test_scenarios_and_logs_hidden_when_disabled(self):
        self.login()
        with override_settings(SHOW_SCENARIOS=False):
            self.assertEqual(self.client.get('/api/events/').status_code, 404)
            self.assertEqual(self.post('scenario', name='open_later', showId='blue-hour').status_code, 400)
            self.assertNotContains(self.client.get('/'), '개발 시나리오')

    def test_malformed_requests(self):
        self.login()
        self.assertEqual(self.client.post('/api/action/', '[]', content_type='application/json').status_code, 400)
