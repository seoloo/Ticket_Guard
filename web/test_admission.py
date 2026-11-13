from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .services import MockRepository


@override_settings(EVENT_PUBLISHER='mock', BOOKING_ADMISSION_BATCH_SIZE=40,
                   BOOKING_ADMISSION_INTERVAL_SECONDS=5)
class AdmissionTests(SimpleTestCase):
    def setUp(self):
        self.clock = patch('web.services.time.monotonic', return_value=100)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.repo = MockRepository()

    def start(self, number):
        return self.repo.start(f'user-{number}', 'blue-hour', f'tab-{number}')

    def test_concurrent_requests_admit_only_forty(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            attempts = list(pool.map(self.start, range(81)))
        self.assertEqual(sum(a['stage'] == 'captcha' for a in attempts), 40)
        waiting = sorted((a for a in attempts if a['stage'] == 'queue'), key=lambda a: a['rank'])
        self.assertEqual(self.repo.queue_status(waiting[0]), (1, 5))
        self.assertEqual(self.repo.queue_status(waiting[-1]), (41, 10))
        self.now.return_value = 104.99
        self.repo.advance_queue()
        self.assertTrue(all(a['stage'] == 'queue' for a in waiting))
        self.now.return_value = 105
        self.repo.advance_queue()
        self.assertTrue(all(a['stage'] == 'captcha' for a in waiting[:40]))
        self.assertEqual(waiting[40]['stage'], 'queue')
        self.assertEqual(self.start(100)['stage'], 'queue')

    def test_no_total_capacity_limit_and_idle_entry_skips_queue(self):
        for batch in range(6):
            self.now.return_value = 100 + batch * 5
            attempts = [self.start(batch * 40 + i) for i in range(40)]
            self.assertTrue(all(a['stage'] == 'captcha' for a in attempts))
        self.assertEqual(sum(a['stage'] == 'captcha' for a in self.repo.attempts.values()), 240)

    def test_retry_does_not_consume_another_slot(self):
        first = self.start(0)
        self.assertIs(self.start(0), first)
        self.assertEqual(self.repo.admission_count, 1)

    def test_expired_waiter_does_not_block_following_user(self):
        for i in range(42):
            self.start(i)
        self.repo.attempts['user-40']['heartbeat'] = 0
        self.now.return_value = 105
        self.repo.advance_queue()
        self.assertEqual(self.repo.attempts['user-40']['stage'], 'expired')
        self.assertEqual(self.repo.attempts['user-41']['stage'], 'captcha')
