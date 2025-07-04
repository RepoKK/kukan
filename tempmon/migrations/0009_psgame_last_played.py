# Generated by Django 4.2.7 on 2024-04-06 04:24

import datetime
from django.db import migrations, models
from django.db.models import Max


def add_last_played(apps, schema_editor):
    # We can't import the Person model directly as it may be a newer
    # version than this migration expects. We use the historical version.
    PsGame = apps.get_model("tempmon", "PsGame")
    for game in PsGame.objects.all():
        game.last_played = game.gamepersessioninfo_set.aggregate(
            Max('session__end_time'))['session__end_time__max']
        if game.last_played:
            game.save()


class Migration(migrations.Migration):

    dependencies = [
        ('tempmon', '0008_psgame_play_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='psgame',
            name='last_played',
            field=models.DateTimeField(
                default=datetime.datetime.fromtimestamp(
                    0, datetime.timezone.utc
                ), verbose_name='Last played'),
            preserve_default=False,
        ),
        migrations.RunPython(add_last_played),
    ]
