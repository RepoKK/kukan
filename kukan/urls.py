from django.urls import path

from . import views
from kukan.views import ExampleCreate, ExampleUpdate, ExampleDelete, ExportView

app_name = 'kukan'
urlpatterns = [
    path('', views.ContactView.as_view()),
    path('kanji/multi/', views.KanjiList.as_view(), name='kanji_multi'),
    path('ajax/get_yomi/', views.get_yomi, name='get_yomi'),
    path('ajax/set_yomi/', views.set_yomi, name='set_yomi'),
    path('ajax/get_goo/', views.get_goo, name='get_goo'),
    path('import/', views.import_file, name='import'),
    path('add_ex/', views.add_ex, name='add_ex'),
    path('example_from_csv/', views.example_from_csv, name='example_from_csv'),
    path('kanji/<str:pk>/', views.KanjiDetail.as_view(), name='kanji_detail'),
    path('reading/<int:pk>/', views.ReadingDetail.as_view(), name='reading_detail'),
    path('example/<int:pk>/', views.ExampleDetail.as_view(), name='example_detail'),
    path('example/search/', views.ExampleList.as_view(), name='example_search'),
    path('example/list/', views.ExampleList2.as_view(), name='example_list'),
    path('example/add/', ExampleCreate.as_view(), name='example-add'),
    path('example/update/<int:pk>/', ExampleUpdate.as_view(), name='example_update'),
    path('example/delete/<int:pk>/', ExampleDelete.as_view(), name='example_delete'),
    path('export/', ExportView.as_view(), name='export'),
    path('export_csv/', views.export_anki_kanji, name='export_anki_csv'),
]
