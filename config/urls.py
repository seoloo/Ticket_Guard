"""
[홍석환] 웹 요청 경로 등록
화면·예매 동작·이벤트 수집·상태 확인 요청을 담당 처리 함수에 연결한다.
"""
from django.urls import path
from web import views
from web.capture_views import capture

urlpatterns = [
    path('health/', views.health),
    path('api/action/', views.action),
    path('api/events/', views.events),
    path('api/capture/', capture),
    path('captcha.png', views.captcha),
    path('auth/check-admin/', views.check_admin),  # 아래 catch-all보다 먼저
    path('api/qa/reset/', views.qa_reset),  # QA 테스트 훅 (Issue #6)
    path('', views.page, {'screen': 'shows'}, name='home'),
    path('<str:screen>/', views.page, name='page'),
    path('<str:screen>/<str:identifier>/', views.page, name='detail'),
]
