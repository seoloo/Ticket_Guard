"""
[홍석환] 웹 애플리케이션 실행 수명 관리
Django 앱 초기화와 이벤트 발행기 종료 처리를 연결한다.
"""
import signal
import threading
from django.apps import AppConfig


class WebConfig(AppConfig):
    name='web'

    def ready(self):
        # Development single-process server: bounded drain on Docker's SIGTERM.
        # Future WSGI/ASGI worker hooks must manage each worker's producer lifecycle.
        if threading.current_thread() is threading.main_thread():
            from .events import publisher
            def terminate(signum,frame):
                publisher.close()
                raise SystemExit(0)
            signal.signal(signal.SIGTERM,terminate)
