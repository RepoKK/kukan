from django.contrib import admin

from .models import Kanji, Reading, Bushu, Classification, YomiType, YomiJoyo, Example


class KanjiInline(admin.TabularInline):
    model = Reading
    extra = 1


class KanjiAdmin(admin.ModelAdmin):
    fieldsets = [
        (None,      {'fields': ['kanji']}),
        ('漢字情報', {'fields': ['bushu', 'kanken_kyu', 'strokes', 'classification', 'update_time', 'jukuji']}),
    ]
    inlines = [KanjiInline]
    list_display = ('kanji', 'bushu', 'kanken_kyu', 'strokes', 'classification')


admin.site.register(Kanji, KanjiAdmin)
admin.site.register(Bushu)
admin.site.register(Classification)
admin.site.register(Reading)
admin.site.register(YomiType)
admin.site.register(YomiJoyo)
admin.site.register(Example)