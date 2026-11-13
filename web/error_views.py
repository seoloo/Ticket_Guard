"""404/500 error pages (ticket stub design).

The error number shown on the page is built from the same requestId that
RequestTelemetryMiddleware records in the server_request event, so a number a
user reports can be found in the dashboard DB (http_events, details.requestId).
"""
import logging
from uuid import uuid4
from django.conf import settings
from django.http import Http404, HttpResponseNotFound, HttpResponseServerError
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger('ticketguard.errors')


def error_code(request_id):
    """'7f3a21c9-....' -> 'ERR-7F3A21C9' (first 8 hex digits of the requestId)."""
    return 'ERR-' + request_id.replace('-', '')[:8].upper()


def _context(request, status):
    request_id = getattr(request, 'capture_request_id', None) or str(uuid4())
    try:
        user = request.session.get('user')
    except Exception:
        user = None
    return {
        'screen': 'error', 'status': status, 'user': user,
        'capture_enabled': settings.CAPTURE_ENABLED,
        'request_id': request_id, 'error_code': error_code(request_id),
        'occurred_at': timezone.localtime(), 'request_path': request.path[:200],
    }


def page_not_found(request, exception=None):
    return HttpResponseNotFound(render_to_string('errors/404.html', _context(request, 404), request))


def server_error(request):
    try:
        return HttpResponseServerError(render_to_string('errors/500.html', _context(request, 500), request))
    except Exception:
        # The error page itself must never raise.
        logger.exception('error_page_render_failed')
        return HttpResponseServerError('<h1>Server Error (500)</h1>', content_type='text/html')


def preview(request, status):
    """DEBUG-only preview. Django uses handler404/500 only when DEBUG=0."""
    if not settings.DEBUG:
        raise Http404
    if status == 500:
        return server_error(request)
    return page_not_found(request)
