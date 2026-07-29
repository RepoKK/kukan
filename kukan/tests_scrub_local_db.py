"""Tests for `scrub_local_db`.

The command rewrites every password in the database. Its guards are the whole
point, so they are tested before its effects: each one is checked in isolation,
and each check asserts that *nothing was modified* when the guard trips.
"""
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from kukan.management.commands.scrub_local_db import CONFIRM_FLAG
from tempmon.models import PsnApiKey


@override_settings(DEBUG=True)
class ScrubGuardsTest(TestCase):
    """Each guard, and the promise that a refusal changes nothing."""

    def setUp(self):
        self.user = User.objects.create_user('someone', password='original')
        self.original_hash = self.user.password

    def assertNothingChanged(self):
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, self.original_hash)
        self.assertTrue(
            User.objects.get(pk=self.user.pk).check_password('original'))

    def test_refuses_without_the_confirmation_flag(self):
        with self.assertRaisesMessage(CommandError, 'rewrites every password'):
            call_command('scrub_local_db')
        self.assertNothingChanged()

    def test_refuses_an_abbreviated_confirmation_flag(self):
        """argparse would otherwise accept `--yes` as an unambiguous prefix,
        which makes the deliberately-long flag pointless."""
        with self.assertRaises(CommandError):
            call_command('scrub_local_db', '--yes')
        self.assertNothingChanged()

    @override_settings(DEBUG=False)
    def test_refuses_when_debug_is_off(self):
        """DEBUG is False in production, so this is the load-bearing guard."""
        with self.assertRaisesMessage(CommandError, 'DEBUG is False'):
            call_command('scrub_local_db', CONFIRM_FLAG)
        self.assertNothingChanged()

    @override_settings(DEBUG=False)
    def test_debug_guard_wins_even_with_confirmation(self):
        """The flag must not be able to talk the command into prod."""
        with self.assertRaises(CommandError):
            call_command('scrub_local_db', CONFIRM_FLAG)
        self.assertNothingChanged()

    def test_refuses_a_production_looking_database_path(self):
        with override_settings(
                DATABASES={'default': {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': '/home/fred/kukan/db.sqlite3'}}), \
                self.assertRaisesMessage(CommandError, 'production location'):
            call_command('scrub_local_db', CONFIRM_FLAG)
        self.assertNothingChanged()


@override_settings(DEBUG=True)
class ScrubEffectsTest(TestCase):
    """What it does once the guards pass."""

    def setUp(self):
        self.alice = User.objects.create_user('alice', password='alice-secret')
        self.bob = User.objects.create_superuser(
            'bob', 'bob@example.com', 'bob-secret')
        # A migration already seeds one PsnApiKey row; start from a known state
        # rather than adding a second.
        PsnApiKey.objects.all().delete()
        PsnApiKey.objects.create(code='a-real-npsso-token')
        Session.objects.create(
            session_key='abc123', session_data='x',
            expire_date=timezone.now() + timezone.timedelta(days=1))

    def scrub(self, **kwargs):
        call_command('scrub_local_db', CONFIRM_FLAG, **kwargs)

    def test_every_password_becomes_the_dev_password(self):
        self.scrub()
        for user in [self.alice, self.bob]:
            user.refresh_from_db()
            self.assertTrue(user.check_password('dev'),
                            f'{user.username} password was not reset')

    def test_original_passwords_no_longer_work(self):
        self.scrub()
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.check_password('alice-secret'))

    def test_password_can_be_chosen(self):
        self.scrub(password='hunter2')
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password('hunter2'))

    def test_password_is_hashed_not_stored_in_the_clear(self):
        """Asserts the configured hasher was used, without naming it: the test
        settings swap in MD5 for speed, so a hard-coded 'pbkdf2_' prefix would
        pin the wrong thing."""
        from django.contrib.auth.hashers import identify_hasher

        self.scrub()
        self.alice.refresh_from_db()
        self.assertNotEqual(self.alice.password, 'dev')
        self.assertIsNotNone(identify_hasher(self.alice.password))

    def test_superuser_status_is_preserved(self):
        """Scrubbing credentials must not change who can do what."""
        self.scrub()
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.is_superuser)

    def test_psn_token_is_reset_to_the_sentinel(self):
        """'__dummy__', not '': tempmon.views compares against that sentinel to
        decide whether to attempt a PSN login at import time."""
        self.scrub()
        self.assertEqual(PsnApiKey.objects.get().code, '__dummy__')

    def test_sessions_are_deleted(self):
        self.scrub()
        self.assertEqual(Session.objects.count(), 0)

    def test_reports_what_it_did(self):
        from io import StringIO

        out = StringIO()
        call_command('scrub_local_db', CONFIRM_FLAG, stdout=out)
        output = out.getvalue()
        self.assertIn('2 password(s) reset', output)
        self.assertIn('1 PSN token(s) blanked', output)
        self.assertIn('1 session(s) deleted', output)

    def test_names_the_accounts_it_reset(self):
        """The scrubbed copy exists to be logged into, and the accounts in it
        are whatever production has — not necessarily the shell user's name.
        Without this you scrub, then guess, then reach for sqlite3."""
        from io import StringIO

        out = StringIO()
        call_command('scrub_local_db', CONFIRM_FLAG, stdout=out)
        output = out.getvalue()
        self.assertIn('alice', output)
        self.assertIn('bob*', output, 'superusers are not marked')

    def test_warns_when_no_account_is_a_superuser(self):
        """smoke_urls defaults to the first superuser, so a copy without one
        needs --username. Say so at scrub time rather than at smoke time."""
        from io import StringIO

        User.objects.update(is_superuser=False)
        out = StringIO()
        call_command('scrub_local_db', CONFIRM_FLAG, stdout=out)
        self.assertIn('No superuser among them', out.getvalue())

    def test_is_idempotent(self):
        self.scrub()
        self.scrub()
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password('dev'))
        self.assertEqual(PsnApiKey.objects.get().code, '__dummy__')
