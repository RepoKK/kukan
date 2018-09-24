from django.urls import path

from . import views

app_name = 'kukan'
urlpatterns = [
    path('', views.Index.as_view()),
    path('stats', views.StatsPage.as_view(), name='stats'),

    path('kanji/list/', views.KanjiListFilter.as_view(), name='kanji_list'),
    path('kanji/<str:pk>/', views.KanjiDetail.as_view(), name='kanji_detail'),

    path('yoji/list/', views.YojiList.as_view(), name='yoji_list'),
    path('yoji/<str:pk>/', views.YojiDetail.as_view(), name='yoji_detail'),
    path('ajax/yoji_anki/', views.yoji_anki, name='yoji_anki'),

    path('example/list/', views.ExampleList.as_view(), name='example_list'),
    path('example/<int:pk>/', views.ExampleDetail.as_view(), name='example_detail'),
    path('example/add/', views.ExampleCreate.as_view(), name='example-add'),
    path('example/update/<int:pk>/', views.ExampleUpdate.as_view(), name='example_update'),

    path('kotowaza/list/', views.KotowazaList.as_view(), name='kotowaza_list'),
    path('kotowaza/<int:pk>/', views.KotowazaDetail.as_view(), name='kotowaza_detail'),
    path('kotowaza/add/', views.KotowazaCreate.as_view(), name='kotowaza-add'),
    path('kotowaza/update/<int:pk>/', views.KotowazaUpdate.as_view(), name='kotowaza_update'),

    path('ajax/get_similar_word/', views.get_similar_word, name='get_similar_word'),
    path('ajax/get_yomi/', views.get_yomi, name='get_yomi'),
    path('ajax/set_yomi/', views.set_yomi, name='set_yomi'),
    path('ajax/get_goo/', views.get_goo, name='get_goo'),
    path('ajax/get_furigana/', views.get_furigana, name='get_furigana'),

    path('test_result/list/', views.TestResultList.as_view(), name='test_result_list'),

    path('export/', views.ExportView.as_view(), name='export'),
]
