import os

import pandas as pd
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from kukan.anki_dj import AnkiProfile
from kukan.exporting import Exporter


class Command(BaseCommand):
    help = 'Sync Anki'

    def add_arguments(self, parser):
        parser.add_argument(
            '--profile',
            dest='profile',
            default='',
            help='Only sync this profile (all defined profiles are sync by default)',
        )
        parser.add_argument(
            '--max_delete_count',
            type=int,
            dest='max_delete_count',
            default='5',
            help='Maximum number of card which can be deleted',
        )

    def handle(self, *args, **options):
        res_dfs = {}
        for profile in options['profile'].split() or AnkiProfile.profile_list():
            dir_to_clear = settings.ANKI_IMPORT_DIR
            list(map(os.unlink, (os.path.join(dir_to_clear, f) for f in os.listdir(dir_to_clear))))

            Exporter('all', profile).export()
            res_dfs[profile] = AnkiProfile(profile, options['max_delete_count']).sync()

        send_mail('Anki sync results', '', 'kukanjiten', ['fr_yjp-div@yahoo.co.jp'], fail_silently=False,
                  html_message=pd.concat(res_dfs).to_html())
