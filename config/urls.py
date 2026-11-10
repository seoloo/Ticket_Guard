from django.urls import path
from web import views
from web.capture_views import capture
from web.board_views import board_page

urlpatterns = [
    path('health/', views.health),
    path('api/action/', views.action),
    path('api/events/', views.events),
    path('api/capture/', capture),
    path('captcha.png', views.captcha),
    path('auth/check-admin/', views.check_admin),  # 아래 catch-all보다 먼저
    path('api/qa/reset/', views.qa_reset),  # QA 테스트 훅 (Issue #6)
    path('', views.page, {'screen': 'shows'}, name='home'),
    path('notices/', board_page, {'board': 'notices'}, name='notices'),
    path('free-board/', board_page, {'board': 'free_board'}, name='free_board'),
    path('<str:screen>/', views.page, name='page'),
    path('<str:screen>/<str:identifier>/', views.page, name='detail'),
]
