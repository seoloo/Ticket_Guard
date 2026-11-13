"""
[홍석환] Django 비동기 서버 진입점
프로젝트 설정을 지정하고 ASGI 애플리케이션을 제공한다.
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.core.asgi import get_asgi_application
application = get_asgi_application()
