"""Tests for the Dropbox helper.

`utils_django/dropbox.py` had no coverage at all. It is thin, but it is the
only path by which the nightly backup leaves the machine, and every one of its
error branches is a place where a failure is logged and swallowed rather than
raised — so a break here is silent by construction.

The `dropbox` SDK is pinned at 12.0.2 and is a refresh candidate. Everything
below mocks at the `dropbox.Dropbox` boundary, which makes the surface the code
depends on explicit: `users_get_current_account`, `files_upload` with a
`WriteMode`, `files_download_to_file`, and the shape of `ApiError.error`.
"""
import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from utils_django import dropbox as dbx_helper


@override_settings(DROPBOX_TOKEN='settings-token')
class DropboxApiTest(TestCase):
    @patch('utils_django.dropbox.dropbox.Dropbox')
    def test_uses_the_token_from_settings_by_default(self, dropbox_cls):
        dbx_helper.dropbox_api()
        dropbox_cls.assert_called_once_with('settings-token')

    @patch('utils_django.dropbox.dropbox.Dropbox')
    def test_explicit_token_overrides_settings(self, dropbox_cls):
        dbx_helper.dropbox_api('explicit-token')
        dropbox_cls.assert_called_once_with('explicit-token')

    @patch('utils_django.dropbox.dropbox.Dropbox')
    def test_validates_the_token_before_returning(self, dropbox_cls):
        """A bad token otherwise only surfaces at the first real call."""
        api = dbx_helper.dropbox_api()
        api.users_get_current_account.assert_called_once_with()

    @patch('utils_django.dropbox.dropbox.Dropbox')
    def test_auth_error_is_logged_and_re_raised(self, dropbox_cls):
        from dropbox.exceptions import AuthError

        error = AuthError('req-id', 'bad token')
        dropbox_cls.return_value.users_get_current_account.side_effect = error

        with self.assertRaises(AuthError), \
                self.assertLogs('utils_django.dropbox', logging.ERROR) as logs:
            dbx_helper.dropbox_api()
        self.assertIn('Invalid access token', logs.output[0])


@override_settings(DROPBOX_TOKEN='settings-token')
class DropboxUploadTest(TestCase):
    """`upload` reads a local file and writes it with overwrite semantics."""

    def setUp(self):
        patcher = patch('utils_django.dropbox.dropbox.Dropbox')
        self.dropbox_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.dbx = self.dropbox_cls.return_value

        open_patcher = patch('builtins.open',
                             new=MagicMock(name='open'))
        self.mock_open = open_patcher.start()
        self.addCleanup(open_patcher.stop)
        self.mock_open.return_value.__enter__.return_value.read.return_value = \
            b'file-contents'

    def test_uploads_the_file_contents(self):
        dbx_helper.upload('/tmp/local.db', '/remote/local.db')
        args, _kwargs = self.dbx.files_upload.call_args
        self.assertEqual(args[0], b'file-contents')
        self.assertEqual(args[1], '/remote/local.db')

    def test_uploads_with_overwrite_mode(self):
        """Backups reuse the same name each day; append would be wrong."""
        from dropbox.files import WriteMode

        dbx_helper.upload('/tmp/local.db', '/remote/local.db')
        self.assertEqual(self.dbx.files_upload.call_args.kwargs['mode'],
                         WriteMode('overwrite'))

    def make_api_error(self, insufficient_space=False, user_message=None):
        from dropbox.exceptions import ApiError

        error = MagicMock()
        error.is_path.return_value = insufficient_space
        error.get_path.return_value.reason.is_insufficient_space.return_value \
            = insufficient_space
        api_error = ApiError('req-id', error, user_message, None)
        return api_error

    def test_insufficient_space_is_logged_and_swallowed(self):
        """SWALLOWED, not raised: a full Dropbox means the nightly backup
        silently does nothing. Pinned as current behaviour."""
        self.dbx.files_upload.side_effect = self.make_api_error(
            insufficient_space=True)

        with self.assertLogs('utils_django.dropbox', logging.ERROR) as logs:
            dbx_helper.upload('/tmp/local.db', '/remote/local.db')
        self.assertIn('insufficient space', logs.output[0])

    def test_other_api_error_logs_the_user_message(self):
        self.dbx.files_upload.side_effect = self.make_api_error(
            user_message='something went wrong')

        with self.assertLogs('utils_django.dropbox', logging.ERROR) as logs:
            dbx_helper.upload('/tmp/local.db', '/remote/local.db')
        self.assertIn('something went wrong', logs.output[0])

    def test_api_error_without_a_user_message_logs_the_error(self):
        self.dbx.files_upload.side_effect = self.make_api_error()

        with self.assertLogs('utils_django.dropbox', logging.ERROR):
            dbx_helper.upload('/tmp/local.db', '/remote/local.db')


@override_settings(DROPBOX_TOKEN='settings-token')
class DropboxDownloadTest(TestCase):
    @patch('utils_django.dropbox.dropbox.Dropbox')
    def test_downloads_to_the_given_path(self, dropbox_cls):
        dbx_helper.download('/remote/f.db', '/tmp/f.db')
        dropbox_cls.return_value.files_download_to_file.assert_called_once_with(
            '/tmp/f.db', '/remote/f.db', None)
