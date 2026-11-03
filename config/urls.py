from django.urls import path
from web import views

urlpatterns = [
    path('health/', views.health),
    path('api/action/', views.action),
    path('api/events/', views.events),
    path('captcha.png', views.captcha),
    path('', views.page, {'screen': 'shows'}, name='home'),
    path('<str:screen>/', views.page, name='page'),
    path('<str:screen>/<str:identifier>/', views.page, name='detail'),
]
