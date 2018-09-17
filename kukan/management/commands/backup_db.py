import sys, os, re
import subprocess
import datetime
import pandas as pd
from collections import namedtuple

from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.mail import send_mail
from django.db import connection
from kukan.exporting import Exporter
from kukan.anki import AnkiProfile

import dropbox


# Backup strategy:
# Keep 2 months of daily backup
# Keep all backups from the 01, 11 and 21 of each months
class DbBackup:
    def __init__(self):
        self.db_name = connection.settings_dict['NAME']
        self.backup_date = None
        self.filename = None
        self.backup_path = None

        self.dbx = dbx = dropbox.Dropbox(settings.DROPBOX_TOKEN)

    def _set_backup_day(self):
        self.backup_date = datetime.datetime.today().strftime('%Y-%m-%d')
        self.filename = 'db.sqlite3_{}'.format(self.backup_date)
        self.backup_path = os.path.join(settings.DB_BACKUP, self.filename)

    def _db_backup(self):
        os_cmd = 'sqlite3 {} ".backup \'{}\'"'.format(self.db_name, self.backup_path)
        try:
            subprocess.run(os_cmd, stdout=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as err:
            print('*** Failed to backup database', err.stdout)
            raise

    def _upload_file_to_dropbox(self, source_file, destination_dir):
        with open(source_file, 'rb') as f:
            data = f.read()
        try:
            self.dbx.files_upload(data, destination_dir, dropbox.files.WriteMode.overwrite, mute=True)
        except dropbox.exceptions.ApiError as err:
            print('*** Dropbox API error', err)
            raise

    def _upload_to_dropbox(self, source_file, destination_dir):
        self._upload_file_to_dropbox(self.backup_path, '/daily/' + self.filename)
        if self.backup_date[-2:] in ['01', '11', '21']:
            self._upload_file_to_dropbox(self.backup_path, '/{}/{}/{}'.format(
                self.backup_date[0:4], self.backup_date[5:7], self.filename))

    def backup_and_upload(self):
        self._set_backup_day()
        self._db_backup()
        self._upload_to_dropbox()


class Command(BaseCommand):
    help = 'Backup SQLite file to Dropbox'

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        DbBackup().backup_and_upload()
