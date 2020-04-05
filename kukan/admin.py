from django.contrib import admin

from kukan.models import TestSource
from .models import Kanji, KanjiDetails, Reading, Bushu, Classification, YomiType, YomiJoyo, Example, Kanken
from .models import Kotowaza, KoukiBushu, TestResult
from .models import Bunrui, Yoji


class KanjiInline(admin.TabularInline):
    model = Reading
    extra = 1


class KanjiDetailsInline(admin.StackedInline):
    model = KanjiDetails
    fk_name = "kanji"
    raw_id_fields = ["std_kanji"]


class KanjiAdmin(admin.ModelAdmin):
    inlines = [KanjiDetailsInline, KanjiInline]
    raw_id_fields = ("bushu", "kouki_bushu")


class ExampleAdmin(admin.ModelAdmin):
    exclude = ("readings",)


class TestResultAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'source', 'score']


admin.site.register(Kanji, KanjiAdmin)
admin.site.register(Bushu)
admin.site.register(KoukiBushu)
admin.site.register(Classification)
admin.site.register(Reading)
admin.site.register(YomiType)
admin.site.register(YomiJoyo)
admin.site.register(Example, ExampleAdmin)
admin.site.register(Kanken)
admin.site.register(Kotowaza)
admin.site.register(Bunrui)
admin.site.register(Yoji)
admin.site.register(TestResult, TestResultAdmin)
admin.site.register(TestSource)