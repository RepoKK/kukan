# Generated by Django 4.2.7 on 2023-12-28 07:01
import pickle

from django.db import migrations


def upgrade_data_points(apps, schema_editor):
    # We can't import the Person model directly as it may be a newer
    # version than this migration expects. We use the historical version.
    PlaySession = apps.get_model("tempmon", "PlaySession")
    for session in PlaySession.objects.all():
        data_dict = pickle.loads(session.data_points)
        new_dict = {k: (*v, -1) for k,v in data_dict.items()}
        session.data_points = pickle.dumps(new_dict)
        session.save()


class Migration(migrations.Migration):

    dependencies = [
        ('tempmon', '0002_psgame'),
    ]

    operations = [
        migrations.RunPython(upgrade_data_points),
    ]
