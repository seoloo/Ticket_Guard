"""QA 테스트 훅 · 켜짐 · 꺼짐 동작 (Issue #6)"""
import json
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from .services import MockRepository, FlowError

HOOKS_ON = dict(QA_TEST_ACCOUNT_COUNT=2, QA_TEST_ACCOUNT_PASSWORD='qa-password', QA_CAPTCHA_FIXED_ANSWER='QA123',
                QUEUE_WAIT_SECONDS=0, QA_RESET_ENABLED=True)
HOOKS_OFF = dict(QA_TEST_ACCOUNT_COUNT=0, QA_TEST_ACCOUNT_PASSWORD='', QA_CAPTCHA_FIXED_ANSWER='',
                 QUEUE_WAIT_SECONDS=12, QA_RESET_ENABLED=False)


@override_settings(EVENT_PUBLISHER='mock', DEMO_ADMIN_USERNAME='qa-admin', DEMO_ADMIN_PASSWORD='admin-password')
class QaTestHookTests(SimpleTestCase):
    def setUp(self):
        self.repo = MockRepository()
        self.patcher = patch('web.views.repo', self.repo)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def login(self, username, password):
        return self.client.post('/api/action/', json.dumps(dict(action='login', username=username, password=password)),
                                content_type='application/json')

    @override_settings(**HOOKS_ON)
    def test_test_accounts_login_within_count(self):
        self.assertEqual(self.login('qa-user-0002', 'qa-password').status_code, 200)
        self.assertEqual(self.client.session['role'], 'customer')
        self.assertEqual(self.login('qa-user-0003', 'qa-password').status_code, 401)
        self.assertEqual(self.login('qa-user-0001', 'wrong').status_code, 401)

    @override_settings(**HOOKS_OFF)
    def test_test_accounts_closed_when_off(self):
        self.assertEqual(self.login('qa-user-0001', '').status_code, 401)

    @override_settings(**HOOKS_ON)
    def test_fixed_captcha_and_zero_queue_wait(self):
        a = self.repo.start('qa-user-0001', 'blue-hour', 'tab-one')
        self.assertEqual(self.repo.tick('qa-user-0001', 'tab-one', a['id'])['stage'], 'captcha')
        self.assertEqual(self.repo.challenge('qa-user-0001', 'tab-one', a['id']), 'QA123')
        with self.assertRaises(FlowError):
            self.repo.verify('qa-user-0001', 'tab-one', a['id'], 'WRONG')
        self.assertEqual(a['wrong'], 1)  # 오답 처리 · 5회 제한은 그대로
        self.assertEqual(self.repo.verify('qa-user-0001', 'tab-one', a['id'], 'qa123')['stage'], 'select')

    @override_settings(**HOOKS_OFF)
    def test_random_captcha_and_default_queue_wait_when_off(self):
        a = self.repo.start('one', 'blue-hour', 'tab-one')
        self.assertEqual(self.repo.tick('one', 'tab-one', a['id'])['stage'], 'queue')
        a['entered'] -= 20
        self.repo.tick('one', 'tab-one', a['id'])
        self.assertNotEqual(self.repo.challenge('one', 'tab-one', a['id']), 'QA123')

    @override_settings(**HOOKS_ON)
    def test_reset_admin_only(self):
        self.repo.sold.add('E5')
        self.repo.start('one', 'blue-hour', 'tab-one')
        self.assertEqual(self.client.post('/api/qa/reset/').status_code, 403)
        self.login('qa-admin', 'admin-password')
        self.assertEqual(self.client.post('/api/qa/reset/').status_code, 200)
        self.assertNotIn('E5', self.repo.sold)
        self.assertEqual((self.repo.attempts, self.repo.remaining), ({}, 28))

    @override_settings(**HOOKS_OFF)
    def test_reset_hidden_when_off(self):
        self.login('qa-admin', 'admin-password')
        self.assertEqual(self.client.post('/api/qa/reset/').status_code, 404)
