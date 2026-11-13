"""Login failure limit per browser: LOGIN_MAX_FAILURES wrong attempts from one
browser (any usernames) lock login in that browser for LOGIN_LOCK_SECONDS.

The browser is identified by a signed random cookie (tg_login). Clearing cookies
starts over; that is accepted for this demo. Single-process memory like
MockRepository, so a server restart clears it.
"""
import time
from functools import wraps
from threading import RLock
from uuid import UUID, uuid4
from django.conf import settings

COOKIE = 'tg_login'
COOKIE_SALT = 'login-guard'
COOKIE_MAX_AGE = 30 * 24 * 3600


class LoginGuard:
    MAX_TRACKED = 10000

    def __init__(self):
        self.lock = RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.entries = {}

    def is_locked(self, client):
        """True while locked. An expired lock starts the count over."""
        with self.lock:
            now = time.monotonic()
            entry = self.entries.get(client)
            if not entry or not entry['locked_until']:
                return False
            if entry['locked_until'] > now:
                return True
            del self.entries[client]
            return False

    def fail(self, client):
        """Count one failure. Returns (failures, locked_now)."""
        with self.lock:
            now = time.monotonic()
            entry = self.entries.get(client)
            # Failures far apart do not add up: the window equals the lock time.
            if entry and now - entry['updated'] > settings.LOGIN_LOCK_SECONDS:
                entry = None
            if entry is None:
                self._make_room(now)
                entry = self.entries[client] = {'failures': 0, 'locked_until': 0, 'updated': now}
            entry['failures'] += 1
            entry['updated'] = now
            if entry['failures'] >= settings.LOGIN_MAX_FAILURES:
                entry['locked_until'] = now + settings.LOGIN_LOCK_SECONDS
                return entry['failures'], True
            return entry['failures'], False

    def succeed(self, client):
        with self.lock:
            self.entries.pop(client, None)

    def _make_room(self, now):
        if len(self.entries) < self.MAX_TRACKED:
            return
        for key, entry in list(self.entries.items()):
            if entry['locked_until'] <= now and now - entry['updated'] > settings.LOGIN_LOCK_SECONDS:
                del self.entries[key]
        if len(self.entries) >= self.MAX_TRACKED:
            del self.entries[min(self.entries, key=lambda k: self.entries[k]['updated'])]


login_guard = LoginGuard()


def login_client(request):
    """This browser's id from the signed cookie; a new id is issued if missing."""
    value = request.get_signed_cookie(COOKIE, default=None, salt=COOKIE_SALT)
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        request.login_client_new = str(uuid4())
        return request.login_client_new


def issue_login_cookie(view):
    """Set the browser id cookie on whatever response the view returns."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        client = getattr(request, 'login_client_new', None)
        if client:
            response.set_signed_cookie(COOKIE, client, salt=COOKIE_SALT, max_age=COOKIE_MAX_AGE,
                                       httponly=True, samesite='Lax', secure=not settings.DEBUG)
        return response
    return wrapped
