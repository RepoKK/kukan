from django.contrib import admin

from .models import Kanji, KanjiDetails, Reading, Bushu, Classification, YomiType, YomiJoyo, Example, Kanken
from .models import KoukiBushu, TestResult
from .models import Bunrui, Yoji


class KanjiInline(admin.TabularInline):
    model = Reading
    extra = 1

class KanjiDetailsInline(admin.StackedInline):
    model = KanjiDetails
    fk_name = "kanji"

class KanjiAdmin(admin.ModelAdmin):
    inlines = [KanjiDetailsInline, KanjiInline]

class ExampleAdmin(admin.ModelAdmin):
    raw_id_fields = ("readings",)

admin.site.register(Kanji, KanjiAdmin)
admin.site.register(Bushu)
admin.site.register(KoukiBushu)
admin.site.register(Classification)
admin.site.register(Reading)
admin.site.register(YomiType)
admin.site.register(YomiJoyo)
admin.site.register(Example, ExampleAdmin)
admin.site.register(Kanken)
admin.site.register(Bunrui)
admin.site.register(Yoji)
admin.site.register(TestResult)
