from django.urls import path

from . import views

app_name = 'wtrack'
urlpatterns = [
    path('summary', views.WtrackMain.as_view(), name='wtrack_main'),
    path('withings_cb', views.withings_auth_cb, name='withings_cb'),
    path('withings_auth_request', views.withings_auth_request, name='withings_auth_request'),
]