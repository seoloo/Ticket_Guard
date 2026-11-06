import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'local-demo-only-change-before-deployment-ticket-guard')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
ROOT_URLCONF = 'config.urls'
INSTALLED_APPS = ['django.contrib.staticfiles', 'web']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware']
MIDDLEWARE.insert(2, 'web.middleware.RequestTelemetryMiddleware')
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'django.template.context_processors.static']}}]
DATABASES = {}  # Phase 1 deliberately has no relational database.
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 3600
CSRF_COOKIE_SAMESITE = 'Lax'
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
ASGI_APPLICATION = 'config.asgi.application'
DEMO_USERNAME = os.environ.get('DEMO_USERNAME', 'ticketguard')
DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'ticketguard-demo')
DEMO_SECOND_USERNAME = os.environ.get('DEMO_SECOND_USERNAME', 'guest')
DEMO_ADMIN_USERNAME = os.environ.get('DEMO_ADMIN_USERNAME', '')
DEMO_ADMIN_PASSWORD = os.environ.get('DEMO_ADMIN_PASSWORD', '')  # 비어 있으면 관리자 로그인 꺼짐
SHOW_SCENARIOS = DEBUG and os.environ.get('SHOW_SCENARIOS', '1') == '1'
# QA 테스트 훅 · DJANGO_DEBUG=1일 때만 · 비어 있으면 꺼짐 (Issue #6)
QUEUE_WAIT_SECONDS = max(int(os.environ.get('QUEUE_WAIT_SECONDS') or 12), 0) if DEBUG else 12
QA_TEST_ACCOUNT_COUNT = min(max(int(os.environ.get('QA_TEST_ACCOUNT_COUNT') or 0), 0), 9999) if DEBUG else 0
QA_TEST_ACCOUNT_PASSWORD = os.environ.get('QA_TEST_ACCOUNT_PASSWORD', '') if DEBUG else ''
QA_CAPTCHA_FIXED_ANSWER = os.environ.get('QA_CAPTCHA_FIXED_ANSWER', '').strip().upper() if DEBUG else ''
QA_RESET_ENABLED = DEBUG and os.environ.get('QA_RESET_ENABLED') == '1'
ATTEMPT_TIMEOUT_SECONDS = 60
EVENT_PUBLISHER = os.environ.get('EVENT_PUBLISHER', 'mock')
KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
KAFKA_EVENTS_TOPIC = os.environ.get('KAFKA_EVENTS_TOPIC', 'ticketguard.events.v1')
KAFKA_CLIENT_ID = os.environ.get('KAFKA_CLIENT_ID', 'ticketguard-web')
KAFKA_DELIVERY_TIMEOUT_MS = int(os.environ.get('KAFKA_DELIVERY_TIMEOUT_MS', '5000'))
EVENT_RECEIPT_TTL_SECONDS = 900
EVENT_RECEIPT_MAX = 2000
EVENT_MAX_ATTEMPTS = 3
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
if not DEBUG and SECRET_KEY.startswith('local-demo'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY before disabling DEBUG.')

# Simulation observation: no field/body sampling or silent truncation.
CAPTURE_ENABLED = os.environ.get('CAPTURE_ENABLED', '1') == '1'
# Preserve existing small Kafka records using transport chunks, not data loss.
CAPTURE_KAFKA_RECORD_BYTES = 16384
# Django's existing memory upload limit is retained, but capture API returns explicit 413.
# No additional collector body-size cap is imposed.
