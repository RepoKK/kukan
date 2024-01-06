from django.contrib import admin

from tempmon.models import PsGame, PlaySession

admin.site.register(PsGame)


@admin.register(PlaySession)
class PlaySessionAdmin(admin.ModelAdmin):
    list_display = ['start_time', 'end_time', 'duration']
