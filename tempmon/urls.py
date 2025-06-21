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
    path('psn_npsso_update/<int:pk>/', views.PsnApiKeyUpdateView.as_view(),
         name='psn_npsso_update'),
    path('game_list/', views.GamesListView.as_view(),
         name='game_list'),
    path('playtime_monthly/', views.PlaytimeMonthlyView.as_view(),
         name='playtime_monthly'),
    path('playtime_yearly/', views.PlaytimeYearlyView.as_view(),
         name='playtime_yearly'),
]
