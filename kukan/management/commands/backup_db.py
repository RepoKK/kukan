import bz2
import datetime
import logging
import os
import re
import subprocess

import dropbox
from django.conf import settings
from django.db import connection
from dropbox import exceptions, files
from pathlib import Path

from utils_django.management_command import FBaseCommand

logger = logging.getLogger(__name__)


# Backup strategy:
# Keep 90days of daily backup
# Keep all backups from the 01, 11 and 21 of each month
class DbBackup:
    daily_days_to_keep = 90

    def __init__(self, db_path: Path, dbx_base_dir: str):
        """
        :param db_path: the full path of the DB file to back up
        :param dbx_base_dir: the directory under which to back up in Dropbox
        """
        self.db_name = db_path
        self.dbx_base_dir = '/' + dbx_base_dir
        self.dbx_daily_folder = self.dbx_base_dir + '/daily'
        self.backup_date = None
        self.filename = None
        self.backup_path = None
        self.compressed_backup = None

        self.dbx = dropbox.Dropbox(settings.DROPBOX_TOKEN)

    def _set_backup_day(self):
        today = datetime.datetime.today()
        self.backup_date = today.strftime('%Y-%m-%d')
        self.filename = f'{self.db_name.name}_{self.backup_date}'
        self.backup_path = Path(settings.DB_BACKUP) / self.filename
        self.compressed_backup = Path(str(self.backup_path) + '.bz2')
        self.string_format = (today - datetime.timedelta(
            days=self.daily_days_to_keep)).strftime('%Y-%m-%d')
        self.daily_keep_cutoff = self.string_format
        logger.info(f'Backup file {self.db_name} for {self.backup_date}, '
                    f'remove daily backup older than {self.daily_keep_cutoff}')

    def _db_backup(self):
        os_cmd = 'sqlite3 {} ".backup \'{}\'"'.format(self.db_name,
                                                      self.backup_path)
        try:
            subprocess.run(os_cmd, shell=True, stdout=subprocess.PIPE,
                           check=True)
            tar_bz2_contents = bz2.compress(open(self.backup_path, 'rb').read())
            with open(self.compressed_backup, "wb") as f:
                f.write(tar_bz2_contents)
        except subprocess.CalledProcessError as err:
            print('*** Failed to backup database', err.stdout)
            logger.error('Failed to backup database: %s', err.output)
            raise

    def _upload_file_to_dropbox(self, source_file, destination_dir):
        with open(source_file, 'rb') as f:
            data = f.read()
        try:
            self.dbx.files_upload(data, destination_dir,
                                  files.WriteMode.overwrite, mute=True)
        except exceptions.ApiError as err:
            print('*** Dropbox API error', err)
            logger.error('Dropbox API error: %s', err)
            raise

    def _upload_to_dropbox(self):
        dbx_filename = self.compressed_backup.name
        self._upload_file_to_dropbox(
            self.compressed_backup,
            f'{self.dbx_daily_folder}/{dbx_filename}'
        )
        if self.backup_date[-2:] in ['01', '11', '21']:
            self._upload_file_to_dropbox(
                self.compressed_backup,
                f'/{self.dbx_base_dir}'
                f'/{self.backup_date[0:4]}'
                f'/{self.backup_date[5:7]}'
                f'/{dbx_filename}')
        os.remove(self.backup_path)
        os.remove(self.compressed_backup)

        for e in ([e for e
                   in self.dbx.files_list_folder(self.dbx_daily_folder).entries
                   if e.name[-14:-4] < self.daily_keep_cutoff]):
            self.dbx.files_delete_v2(e.path_lower)
            logger.info('Remove file: %s', e.path_lower)

        
        for e in self.dbx.files_list_folder(self.dbx_base_dir).entries:
            year = re.match('(20[0-9][0-9])', e.name)
            if year: 
                if datetime.datetime.today().year - int(year[1]) > 2:
                    self.dbx.files_delete_v2(e.path_lower)

    def backup_and_upload(self):
        self._set_backup_day()
        self._db_backup()
        self._upload_to_dropbox()


class Command(FBaseCommand):
    help = 'Backup SQLite file to Dropbox'

    def add_arguments(self, parser):
        pass

    def handle_cmd(self, *args, **options):
        DbBackup(Path(connection.settings_dict['NAME']),
                 'DjangoDB').backup_and_upload()

        anki_db_name = 'collection.anki2'
        for account, acc_details in settings.ANKI_ACCOUNTS.items():
            if acc_details['backup']:
                DbBackup(Path(settings.ANKI_DB_DIR) / account / anki_db_name,
                         'Anki/' + account).backup_and_upload()

