from django.contrib import admin

from tempmon.models import PsGame, PlaySession, GamePerSessionInfo


@admin.register(PsGame)
class PsGameAdmin(admin.ModelAdmin):
    list_display = ['name', 'title_id', 'play_time']


@admin.register(PlaySession)
class PlaySessionAdmin(admin.ModelAdmin):
    list_display = ['start_time', 'end_time', 'duration']


@admin.register(GamePerSessionInfo)
class GamePerSessionInfoAdmin(admin.ModelAdmin):
    def session_time(self, obj):
        return obj.session.start_time

    list_display = ['session_time', 'game', 'duration']