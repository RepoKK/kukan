from django.urls import path

from tempmon import views

urlpatterns = [
    path('add_temp_point/', views.add_temp_point, name='add_temp_point'),
    path('session_list/', views.PlaySessionListView.as_view(),
         name='session_list'),
    path('session/<int:pk>/', views.PlaySessionGraphView.as_view(),
         name='session'),
    path('session/<int:pk>/details', views.PlaySessionDetailsView.as_view(),
         name='session_details'),
]

