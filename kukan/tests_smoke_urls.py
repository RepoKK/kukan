"""Tests for the `smoke_urls` management command.

`smoke_urls` is the breadth-first net the later stages lean on: after a
dependency or template change it GETs every no-argument page and reports what
broke. That makes it load-bearing, and an untested checker that silently stops
checking is worse than no checker at all — it reports success either way.

The failure mode to guard against specifically: the command used to abort on
the first view that raised, because Django's test `Client` re-raises view
exceptions by default. It then reported nothing at all. `raise_request_exception
=False` is what turns that into a collected 500, and it is asserted below.
"""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase

from kukan.management.commands.smoke_urls import DEFAULT_SKIP, iter_url_names


class IterUrlNamesTest(TestCase):
    """Walks the real URLconf and yields fully-qualified names."""

    def setUp(self):
        from django.urls import get_resolver
        self.names = set(iter_url_names(get_resolver()))

    def test_namespaced_names_are_qualified(self):
        self.assertIn('kukan:kanji_list', self.names)
        self.assertIn('bustime:bustime_main', self.names)

    def test_unnamespaced_names_are_bare(self):
        self.assertIn('login', self.names)
        self.assertIn('add_temp_point', self.names)

    def test_nested_admin_urls_are_reached(self):
        """Proves the resolver recursion descends into included URLconfs."""
        self.assertTrue(any(n.startswith('admin:') for n in self.names))

    def test_every_skip_entry_still_exists(self):
        """Stops DEFAULT_SKIP from silently exempting a renamed view."""
        self.assertEqual(set(DEFAULT_SKIP) - self.names, set())


class SmokeUrlsCommandTest(TestCase):
    fixtures = ['baseline', '閲']

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            'admin_user', 'admin@example.com', 'pwd')

    def run_command(self, **kwargs):
        out, err = StringIO(), StringIO()
        call_command('smoke_urls', stdout=out, stderr=err, **kwargs)
        return out.getvalue()

    def test_reports_a_summary(self):
        output = self.run_command()
        self.assertRegex(output,
                         r'\d+ URLs checked, 0 failed, \d+ skipped')

    def test_verbose_mode_lists_every_url(self):
        output = self.run_command(verbosity=2)
        self.assertIn('kukan:stats', output)
        self.assertIn('skip', output)

    def test_skipped_urls_are_reported_with_a_reason(self):
        output = self.run_command(verbosity=2)
        self.assertIn('ajax endpoint', output)

    def test_extra_skip_is_honoured(self):
        output = self.run_command(verbosity=2, skip=['kukan:stats'])
        self.assertIn('skipped on the command line', output)

    def test_admin_urls_are_not_checked(self):
        """Django's own admin is not this project's code to smoke-test."""
        output = self.run_command(verbosity=2)
        self.assertNotIn('admin:', output)

    def test_named_user_is_used(self):
        User.objects.create_user('someone', password='pwd')
        with patch('django.test.Client.force_login') as force_login:
            self.run_command(username='someone')
        self.assertEqual(force_login.call_args.args[0].username, 'someone')

    def test_unknown_user_is_an_error(self):
        with self.assertRaisesMessage(CommandError, 'No such user: nobody'):
            self.run_command(username='nobody')

    def test_no_superuser_is_an_error(self):
        User.objects.filter(is_superuser=True).delete()
        with self.assertRaisesMessage(CommandError, 'No superuser found'):
            self.run_command()

    def test_defaults_to_the_first_superuser(self):
        with patch('django.test.Client.force_login') as force_login:
            self.run_command()
        self.assertEqual(force_login.call_args.args[0], self.superuser)


class SmokeUrlsFailureReportingTest(TestCase):
    fixtures = ['baseline', '閲']

    def setUp(self):
        User.objects.create_superuser('admin_user', 'a@example.com', 'pwd')

    def run_expecting_failure(self, status_code=500):
        """Force every checked URL to fail, and capture the report."""
        out = StringIO()
        with patch('django.test.Client.get') as client_get:
            client_get.return_value.status_code = status_code
            with self.assertRaises(CommandError) as ctx:
                call_command('smoke_urls', stdout=out, verbosity=1)
        return out.getvalue(), str(ctx.exception)

    def test_failures_raise_a_command_error(self):
        _, message = self.run_expecting_failure()
        self.assertRegex(message, r'\d+ of \d+ URLs failed')

    def test_failures_are_listed_individually(self):
        output, _ = self.run_expecting_failure()
        self.assertIn('500', output)
        self.assertIn('kukan:stats', output)

    def test_client_of_the_walk_does_not_reraise_view_exceptions(self):
        """The regression that made the command report nothing at all.

        With the default Client, one view raising aborts the whole walk. The
        command must build its Client with raise_request_exception=False so a
        broken view is collected as a 500 and the remaining URLs still get
        checked.
        """
        with patch('kukan.management.commands.smoke_urls.Client') as client_cls:
            client_cls.return_value.get.return_value.status_code = 200
            call_command('smoke_urls', stdout=StringIO())
        self.assertEqual(client_cls.call_args.kwargs,
                         {'raise_request_exception': False})

    def test_a_single_broken_view_does_not_stop_the_walk(self):
        """End to end: a view that raises is reported, and the walk continues.

        The exception is raised inside the view rather than from Client.get,
        because it is Django's request handling that turns it into a 500 —
        patching the client method would bypass the mechanism under test.
        """
        out = StringIO()
        with patch('kukan.views.StatsPage.get_context_data',
                   side_effect=RuntimeError('view exploded')), \
                self.assertRaises(CommandError) as ctx:
            call_command('smoke_urls', stdout=out, verbosity=2)

        output = out.getvalue()
        self.assertIn('500  kukan:stats', output)
        self.assertIn('1 of ', str(ctx.exception))
        # Other URLs were still visited and passed.
        self.assertIn('200  kukan:index', output)

    def test_redirects_are_not_failures(self):
        """Only >= 400 counts; a 302 to login is a normal response here."""
        out = StringIO()
        with patch('django.test.Client.get') as client_get:
            client_get.return_value.status_code = 302
            call_command('smoke_urls', stdout=out)
        self.assertIn('0 failed', out.getvalue())
