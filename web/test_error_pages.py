from unittest.mock import patch
from django.test import SimpleTestCase, Client, override_settings
from .error_views import error_code


@override_settings(EVENT_PUBLISHER='mock')
class ErrorPageTests(SimpleTestCase):
    def test_unknown_url_uses_ticket_404(self):
        for url in ('/no/such/page/', '/unknown-screen/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, 'errors/404.html')
                self.assertContains(response, '찾으시는 무대가 없어요', status_code=404)
                self.assertContains(response, url, status_code=404)
                self.assertContains(response, '/static/errors.css', status_code=404)

    def test_404_request_path_is_escaped(self):
        response = self.client.get('/%3Cb%3Ex%3C/b%3E/')
        self.assertContains(response, '&lt;b&gt;x&lt;/b&gt;', status_code=404)
        self.assertNotContains(response, '<b>x</b>', status_code=404)

    @override_settings(CAPTURE_ENABLED=True)
    def test_500_error_code_matches_captured_request_id(self):
        client = Client(raise_request_exception=False)
        with patch('web.views.render', side_effect=RuntimeError('boom')):
            response = client.get('/')
        self.assertEqual(response.status_code, 500)
        self.assertTemplateUsed(response, 'errors/500.html')
        self.assertContains(response, '잠시 공연이 지연되고 있어요', status_code=500)
        request_id = response['X-Request-ID']
        self.assertContains(response, error_code(request_id), status_code=500)
        self.assertContains(response, f'data-request-id="{request_id}"', status_code=500)
        self.assertNotContains(response, 'boom', status_code=500)

    @override_settings(CAPTURE_ENABLED=False)
    def test_500_renders_without_capture(self):
        client = Client(raise_request_exception=False)
        with patch('web.views.render', side_effect=RuntimeError('boom')):
            response = client.get('/')
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, 'ERR-', status_code=500)

    def test_error_code_format(self):
        self.assertEqual(error_code('7f3a21c9-0000-4000-8000-000000000000'), 'ERR-7F3A21C9')

    def test_preview_only_in_debug(self):
        self.assertTemplateUsed(self.client.get('/dev/errors/500/'), 'errors/404.html')
        with override_settings(DEBUG=True):
            self.assertEqual(self.client.get('/dev/errors/404/').status_code, 404)
            response = self.client.get('/dev/errors/500/')
            self.assertEqual(response.status_code, 500)
            self.assertTemplateUsed(response, 'errors/500.html')
