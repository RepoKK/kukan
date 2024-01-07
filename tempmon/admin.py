from django.contrib import admin

from tempmon.models import PsGame, PlaySession, GamePerSessionInfo

admin.site.register(PsGame)


@admin.register(PlaySession)
class PlaySessionAdmin(admin.ModelAdmin):
    list_display = ['start_time', 'end_time', 'duration']


@admin.register(GamePerSessionInfo)
class GamePerSessionInfoAdmin(admin.ModelAdmin):
    list_display = ['session', 'game', 'duration']