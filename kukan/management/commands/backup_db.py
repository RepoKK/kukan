import sys, os, re, bz2
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
# Keep 90days of daily backup
# Keep all backups from the 01, 11 and 21 of each months
class DbBackup:
    dbx_daily_folder = '/daily'
    daily_days_to_keep = 90

    def __init__(self):
        self.db_name = connection.settings_dict['NAME']
        self.backup_date = None
        self.filename = None
        self.backup_path = None
        self.compressed_backup = None

        self.dbx = dbx = dropbox.Dropbox(settings.DROPBOX_TOKEN)

    def _set_backup_day(self):
        today = datetime.datetime.today()
        self.backup_date = today.strftime('%Y-%m-%d')
        self.filename = 'db.sqlite3_{}'.format(self.backup_date)
        self.backup_path = os.path.join(settings.DB_BACKUP, self.filename)
        self.compressed_backup = self.backup_path + '.bz2'
        self.daily_keep_cutoff = (
                today - datetime.timedelta(days=self.daily_days_to_keep)).strftime('%Y-%m-%d')

    def _db_backup(self):
        os_cmd = 'sqlite3 {} ".backup \'{}\'"'.format(self.db_name, self.backup_path)
        try:
            subprocess.run(os_cmd, shell=True, stdout=subprocess.PIPE, check=True)
            tarbz2contents = bz2.compress(open(self.backup_path, 'rb').read())
            with open(self.compressed_backup, "wb") as f:
                f.write(tarbz2contents)
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

    def _upload_to_dropbox(self):
        dbx_filename = os.path.split(self.compressed_backup)[-1]
        self._upload_file_to_dropbox(self.compressed_backup, '/daily/' + dbx_filename)
        if self.backup_date[-2:] in ['01', '11', '21']:
            self._upload_file_to_dropbox(self.compressed_backup, '/{}/{}/{}'.format(
                self.backup_date[0:4], self.backup_date[5:7], dbx_filename))
        os.remove(self.backup_path)
        os.remove(self.compressed_backup)

        for e in ([e for e in self.dbx.files_list_folder(self.dbx_daily_folder).entries
                   if e.name[-14:-4] < self.daily_keep_cutoff]):
            self.dbx.files_delete_v2(e.path_lower)

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
