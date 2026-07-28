"""Tests for the nightly `backup_db` command.

This is the job that runs at 03:03 every morning and is the only copy of the
database that leaves the machine. It had no coverage.

The retention rules are the interesting part, because they *delete* things:

* every backup goes to `<base>/daily/`, and dailies older than 45 days are
  removed;
* backups dated the 01st, 11th or 21st are additionally copied to
  `<base>/<year>/<month>/` and are never pruned by the daily rule;
* top-level year folders more than two years old are deleted outright.

A bug in any of those is destructive and, running from cron, would be noticed
long after the fact. The tests drive the real logic against a mocked Dropbox
client and assert on which paths get deleted, which is the part worth being
sure about.

Note the class docstring in the command says "Keep 90days of daily backup"
while `daily_days_to_keep` is 45. The code is what runs, so 45 is what is
asserted here; the comment is stale.
"""
import datetime as dt
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from freezegun import freeze_time

from kukan.management.commands.backup_db import DbBackup


def dropbox_entry(name, path_lower=None):
    """Stand-in for a Dropbox FileMetadata entry."""
    entry = MagicMock()
    entry.name = name
    entry.path_lower = path_lower or f'/djangodb/daily/{name.lower()}'
    return entry


class DbBackupTestBase(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

        patcher = patch(
            'kukan.management.commands.backup_db.dropbox.Dropbox')
        self.dropbox_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.dbx = self.dropbox_cls.return_value
        self.dbx.files_list_folder.return_value.entries = []

    def make_backup(self, db_name='db.sqlite3', base_dir='DjangoDB'):
        with override_settings(DB_BACKUP=self.tmpdir.name, DROPBOX_TOKEN='tok'):
            return DbBackup(Path(f'/srv/{db_name}'), base_dir)

    def run_backup(self, backup, frozen_date):
        """Run the whole cycle with sqlite3 and compression stubbed out."""
        def fake_sqlite_backup(cmd, **kwargs):
            # The real command shells out to `sqlite3 ... .backup`; write a
            # placeholder at the destination so the compression step has input.
            destination = cmd.split("'")[1]
            Path(destination).write_bytes(b'fake-sqlite-content')
            return MagicMock(returncode=0)

        with override_settings(DB_BACKUP=self.tmpdir.name), \
                freeze_time(frozen_date), \
                patch('kukan.management.commands.backup_db.subprocess.run',
                      side_effect=fake_sqlite_backup):
            backup.backup_and_upload()


class TestBackupNaming(DbBackupTestBase):
    def test_filename_carries_the_database_name_and_date(self):
        backup = self.make_backup()
        with freeze_time('2026-03-09 03:03:00'), \
                override_settings(DB_BACKUP=self.tmpdir.name):
            backup._set_backup_day()
        self.assertEqual(backup.filename, 'db.sqlite3_2026-03-09')
        self.assertEqual(backup.compressed_backup.name,
                         'db.sqlite3_2026-03-09.bz2')

    def test_daily_cutoff_is_forty_five_days_back(self):
        backup = self.make_backup()
        with freeze_time('2026-03-09 03:03:00'), \
                override_settings(DB_BACKUP=self.tmpdir.name):
            backup._set_backup_day()
        expected = (dt.date(2026, 3, 9) - dt.timedelta(days=45)).isoformat()
        self.assertEqual(backup.daily_keep_cutoff, expected)
        self.assertEqual(backup.daily_keep_cutoff, '2026-01-23')

    def test_dropbox_folders_are_derived_from_the_base_dir(self):
        backup = self.make_backup(base_dir='Anki/Fred')
        self.assertEqual(backup.dbx_base_dir, '/Anki/Fred')
        self.assertEqual(backup.dbx_daily_folder, '/Anki/Fred/daily')


class TestBackupUpload(DbBackupTestBase):
    def uploaded_paths(self):
        return [call.args[1] for call in self.dbx.files_upload.call_args_list]

    def test_ordinary_day_uploads_only_to_daily(self):
        backup = self.make_backup()
        self.run_backup(backup, '2026-03-09 03:03:00')
        self.assertEqual(
            self.uploaded_paths(),
            ['/DjangoDB/daily/db.sqlite3_2026-03-09.bz2'])

    def test_first_of_the_month_is_also_archived(self):
        backup = self.make_backup()
        self.run_backup(backup, '2026-03-01 03:03:00')
        self.assertEqual(
            self.uploaded_paths(),
            ['/DjangoDB/daily/db.sqlite3_2026-03-01.bz2',
             '/DjangoDB/2026/03/db.sqlite3_2026-03-01.bz2'])

    def test_eleventh_and_twenty_first_are_also_archived(self):
        for day in ['11', '21']:
            with self.subTest(day=day):
                self.dbx.files_upload.reset_mock()
                backup = self.make_backup()
                self.run_backup(backup, f'2026-03-{day} 03:03:00')
                self.assertEqual(len(self.uploaded_paths()), 2)

    def test_other_days_are_not_archived(self):
        for day in ['02', '10', '12', '20', '22', '28']:
            with self.subTest(day=day):
                self.dbx.files_upload.reset_mock()
                backup = self.make_backup()
                self.run_backup(backup, f'2026-03-{day} 03:03:00')
                self.assertEqual(len(self.uploaded_paths()), 1)

    def test_local_files_are_removed_after_upload(self):
        """The box has limited disk; leaving these would fill it."""
        backup = self.make_backup()
        self.run_backup(backup, '2026-03-09 03:03:00')
        self.assertEqual(os.listdir(self.tmpdir.name), [])

    def test_uploaded_payload_is_bz2_compressed(self):
        import bz2

        backup = self.make_backup()
        self.run_backup(backup, '2026-03-09 03:03:00')
        payload = self.dbx.files_upload.call_args_list[0].args[0]
        self.assertEqual(bz2.decompress(payload), b'fake-sqlite-content')

    def test_sqlite_failure_propagates(self):
        """A failed dump must not be uploaded as if it had worked."""
        import subprocess

        backup = self.make_backup()
        with override_settings(DB_BACKUP=self.tmpdir.name), \
                freeze_time('2026-03-09'), \
                patch('kukan.management.commands.backup_db.subprocess.run',
                      side_effect=subprocess.CalledProcessError(1, 'sqlite3')):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.backup_and_upload()
        self.dbx.files_upload.assert_not_called()


class TestDailyRetention(DbBackupTestBase):
    """Which daily backups get deleted. The destructive half of the job."""

    def deleted_paths(self):
        return [call.args[0]
                for call in self.dbx.files_delete_v2.call_args_list]

    def set_daily_entries(self, names):
        def list_folder(folder):
            result = MagicMock()
            result.entries = ([dropbox_entry(n) for n in names]
                              if folder.endswith('/daily') else [])
            return result
        self.dbx.files_list_folder.side_effect = list_folder

    def test_backups_older_than_the_cutoff_are_deleted(self):
        self.set_daily_entries(['db.sqlite3_2025-12-01.bz2',
                                'db.sqlite3_2026-03-08.bz2'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(self.deleted_paths(),
                         ['/djangodb/daily/db.sqlite3_2025-12-01.bz2'])

    def test_backups_inside_the_window_are_kept(self):
        self.set_daily_entries(['db.sqlite3_2026-02-01.bz2',
                                'db.sqlite3_2026-03-08.bz2'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(self.deleted_paths(), [])

    def test_the_cutoff_date_itself_is_kept(self):
        """The comparison is strictly less-than, so the boundary survives."""
        self.set_daily_entries(['db.sqlite3_2026-01-23.bz2'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(self.deleted_paths(), [])

    def test_the_day_before_the_cutoff_is_deleted(self):
        self.set_daily_entries(['db.sqlite3_2026-01-22.bz2'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(len(self.deleted_paths()), 1)

    def test_dates_are_read_from_a_fixed_offset_in_the_filename(self):
        """`e.name[-14:-4]` — the date is located by slicing, not parsing, so
        a change to the filename format silently changes what gets deleted."""
        self.set_daily_entries(['db.sqlite3_2025-01-01.bz2'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(len(self.deleted_paths()), 1)


class TestYearlyRetention(DbBackupTestBase):
    """Year folders more than two years old are removed wholesale."""

    def deleted_paths(self):
        return [call.args[0]
                for call in self.dbx.files_delete_v2.call_args_list]

    def set_base_entries(self, names):
        def list_folder(folder):
            result = MagicMock()
            if folder.endswith('/daily'):
                result.entries = []
            else:
                result.entries = [
                    dropbox_entry(n, path_lower=f'/djangodb/{n.lower()}')
                    for n in names]
            return result
        self.dbx.files_list_folder.side_effect = list_folder

    def test_year_folders_older_than_two_years_are_deleted(self):
        self.set_base_entries(['2022', '2023', '2024', '2025', '2026'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(self.deleted_paths(),
                         ['/djangodb/2022', '/djangodb/2023'])

    def test_the_two_year_boundary_is_kept(self):
        self.set_base_entries(['2024'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(self.deleted_paths(), [])

    def test_non_year_entries_are_left_alone(self):
        """'daily' lives in the same folder and must never be matched."""
        self.set_base_entries(['daily', 'notes.txt', '1999'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(self.deleted_paths(), [])

    def test_only_years_beginning_with_20_are_recognised(self):
        """The regex is '(20[0-9][0-9])', anchored at the start of the name."""
        self.set_base_entries(['1999', '3000'])
        self.run_backup(self.make_backup(), '2026-03-09 03:03:00')
        self.assertEqual(self.deleted_paths(), [])


class TestBackupCommand(DbBackupTestBase):
    """The command backs up the Django DB plus each opted-in Anki account."""

    @override_settings(ANKI_ACCOUNTS={
        'Ayumi': {'user': 'a@x.com', 'password': 'p', 'backup': True},
        'Fred': {'user': 'f@x.com', 'password': 'p', 'backup': True},
        'Test2': {'user': 't@x.com', 'password': 'p', 'backup': False},
    })
    @patch('kukan.management.commands.backup_db.DbBackup')
    def test_backs_up_the_django_db_and_only_opted_in_accounts(
            self, db_backup_cls):
        from kukan.management.commands.backup_db import Command

        Command().handle_cmd()

        base_dirs = [call.args[1] for call in db_backup_cls.call_args_list]
        self.assertEqual(base_dirs, ['DjangoDB', 'Anki/Ayumi', 'Anki/Fred'])
        self.assertEqual(db_backup_cls.return_value
                         .backup_and_upload.call_count, 3)
