from django.urls import path

from . import views

app_name = 'bustime'
urlpatterns = [
    path('main', views.BusTimeMain.as_view(), name='bustime_main'),
]