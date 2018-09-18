import sys, os, re
import pandas as pd
from collections import namedtuple

from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.mail import send_mail
from kukan.exporting import Exporter
from kukan.anki import AnkiProfile


class Command(BaseCommand):
    help = 'Sync Anki'

    def add_arguments(self, parser):
        parser.add_argument(
            '--profile',
            dest='profile',
            default='',
            help='Only sync this profile (all defined profiles are sync by default)',
        )

    def handle(self, *args, **options):
        res_dfs = {}
        for profile in options['profile'].split() or AnkiProfile.profile_list():
            dir_to_clear = settings.ANKI_IMPORT_DIR
            list(map(os.unlink, (os.path.join(dir_to_clear, f) for f in os.listdir(dir_to_clear))))

            Exporter('all', profile).export()
            res_dfs[profile] = AnkiProfile(profile).sync()

        send_mail('Anki sync results', '', 'kukanjiten', ['fr_yjp-div@yahoo.co.jp'], fail_silently=False,
                  html_message=pd.concat(res_dfs).to_html())
