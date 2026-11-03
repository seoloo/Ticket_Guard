import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'local-demo-only-change-before-deployment-ticket-guard')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
ROOT_URLCONF = 'config.urls'
INSTALLED_APPS = ['django.contrib.staticfiles', 'web']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware']
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
SHOW_SCENARIOS = DEBUG and os.environ.get('SHOW_SCENARIOS', '1') == '1'
QUEUE_WAIT_SECONDS = 12
ATTEMPT_TIMEOUT_SECONDS = 60
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
if not DEBUG and SECRET_KEY.startswith('local-demo'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY before disabling DEBUG.')
