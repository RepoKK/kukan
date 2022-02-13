from django.urls import path

from . import views

app_name = 'bustime'
urlpatterns = [
    path('main', views.BusTimeMain.as_view(), name='bustime_main'),
    path('get_time_to_next_hana/', views.get_time_to_next_hana,
         name='get_time_to_next_hana'),
]