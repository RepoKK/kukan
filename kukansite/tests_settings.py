"""Tests for the settings package and the environment reader.

The point of stage 4 is that production *cannot* start misconfigured. What it
replaced silently degraded instead:

    try:
        from kukansite.settings_prod import *
    except ImportError:
        pass

with `DEBUG = True` and `ALLOWED_HOSTS = ['*']` above it, so any ImportError
inside settings_prod.py served Django debug pages — stack traces, settings and
SQL — to the internet.

`prod.py` is therefore imported here in a subprocess with a controlled
environment, and asserted to raise when a variable is missing. That is a real
import of the real module: mocking it would test the mock.
"""
import os
import subprocess
import sys
import textwrap

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from kukansite.env import env, env_bool, env_int, env_list

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The full set prod.py requires. Individual tests remove one at a time.
COMPLETE_PROD_ENV = {
    'DJANGO_SECRET_KEY': 'a-secret-key-for-tests',
    'DJANGO_ALLOWED_HOSTS': 'kukanjiten.com,www.kukanjiten.com',
    'DROPBOX_TOKEN': 'dbx',
    'TEMPMON_API_KEY': 'sensor',
    'ANKI_AYUMI_USER': 'a@x.com',
    'ANKI_AYUMI_PASSWORD': 'p1',
    'ANKI_FRED_USER': 'f@x.com',
    'ANKI_FRED_PASSWORD': 'p2',
    'ANKI_TEST2_USER': 't@x.com',
    'ANKI_TEST2_PASSWORD': 'p3',
}


def load_prod_settings(env_overrides, remove=()):
    """Import kukansite.settings.prod in a clean subprocess.

    Returns (returncode, stdout, stderr). A subprocess is used because Django
    settings are process-global and already configured in this one.
    """
    child_env = {
        'PATH': os.environ.get('PATH', ''),
        'HOME': os.environ.get('HOME', ''),
        'PYTHONPATH': REPO_ROOT,
        'DJANGO_SETTINGS_MODULE': 'kukansite.settings.prod',
    }
    child_env.update(env_overrides)
    for name in remove:
        child_env.pop(name, None)

    # The module is imported directly rather than through django.setup():
    # prod.py only imports base.py and os, so the app registry is not needed,
    # and skipping it takes this from ~4s per call to ~0.2s. There are eleven
    # calls in this file.
    script = textwrap.dedent("""
        import kukansite.settings.prod as prod
        print('DEBUG=%s' % prod.DEBUG)
        print('ALLOWED_HOSTS=%s' % ','.join(prod.ALLOWED_HOSTS))
        print('SSL_REDIRECT=%s' % prod.SECURE_SSL_REDIRECT)
        print('HAS_SETTINGS_PROD_FALLBACK=%s' % hasattr(prod, 'PSN_TOKEN'))
    """)
    result = subprocess.run(
        [sys.executable, '-c', script],
        env=child_env, capture_output=True, text=True, cwd=REPO_ROOT,
        timeout=120, check=False)
    return result.returncode, result.stdout, result.stderr


class EnvReaderTest(SimpleTestCase):
    """`kukansite.env` — the dozen lines that replace an env library."""

    def setUp(self):
        self.saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(),
                                 os.environ.update(self.saved)))

    def test_returns_the_value(self):
        os.environ['KUKAN_TEST_VAR'] = 'value'
        self.assertEqual(env('KUKAN_TEST_VAR'), 'value')

    def test_missing_required_variable_raises(self):
        os.environ.pop('KUKAN_TEST_VAR', None)
        with self.assertRaises(ImproperlyConfigured):
            env('KUKAN_TEST_VAR')

    def test_error_names_the_variable_and_where_it_comes_from(self):
        os.environ.pop('KUKAN_TEST_VAR', None)
        with self.assertRaises(ImproperlyConfigured) as ctx:
            env('KUKAN_TEST_VAR')
        message = str(ctx.exception)
        self.assertIn('KUKAN_TEST_VAR', message)
        self.assertIn('/etc/kukan/kukan.env', message)

    def test_default_is_used_when_unset(self):
        os.environ.pop('KUKAN_TEST_VAR', None)
        self.assertEqual(env('KUKAN_TEST_VAR', 'fallback'), 'fallback')

    def test_none_is_a_usable_default(self):
        """The sentinel exists so `default=None` is distinguishable from
        'no default given'."""
        os.environ.pop('KUKAN_TEST_VAR', None)
        self.assertIsNone(env('KUKAN_TEST_VAR', None))

    def test_env_bool_true_values(self):
        for raw in ['1', 'true', 'TRUE', 'yes', 'on', ' True ']:
            os.environ['KUKAN_TEST_VAR'] = raw
            self.assertIs(env_bool('KUKAN_TEST_VAR'), True, raw)

    def test_env_bool_false_values(self):
        for raw in ['0', 'false', 'FALSE', 'no', 'off']:
            os.environ['KUKAN_TEST_VAR'] = raw
            self.assertIs(env_bool('KUKAN_TEST_VAR'), False, raw)

    def test_env_bool_rejects_nonsense(self):
        """'maybe' must not quietly become True, which is how a debug flag
        gets left on in production."""
        os.environ['KUKAN_TEST_VAR'] = 'maybe'
        with self.assertRaises(ImproperlyConfigured):
            env_bool('KUKAN_TEST_VAR')

    def test_env_bool_passes_through_a_bool_default(self):
        os.environ.pop('KUKAN_TEST_VAR', None)
        self.assertIs(env_bool('KUKAN_TEST_VAR', True), True)

    def test_env_int(self):
        os.environ['KUKAN_TEST_VAR'] = '42'
        self.assertEqual(env_int('KUKAN_TEST_VAR'), 42)

    def test_env_int_rejects_non_numeric(self):
        os.environ['KUKAN_TEST_VAR'] = 'lots'
        with self.assertRaises(ImproperlyConfigured):
            env_int('KUKAN_TEST_VAR')

    def test_env_list_splits_and_strips(self):
        os.environ['KUKAN_TEST_VAR'] = 'a, b ,c'
        self.assertEqual(env_list('KUKAN_TEST_VAR'), ['a', 'b', 'c'])

    def test_env_list_drops_empty_entries(self):
        """A trailing comma is the commonest hand-editing slip in an env file
        and must not produce an empty ALLOWED_HOSTS entry."""
        os.environ['KUKAN_TEST_VAR'] = 'a,,b,'
        self.assertEqual(env_list('KUKAN_TEST_VAR'), ['a', 'b'])

    def test_env_list_passes_through_a_list_default(self):
        os.environ.pop('KUKAN_TEST_VAR', None)
        self.assertEqual(env_list('KUKAN_TEST_VAR', ['x']), ['x'])


class ProdSettingsTest(SimpleTestCase):
    """Imports the real prod module in a subprocess."""

    def test_loads_with_a_complete_environment(self):
        code, stdout, stderr = load_prod_settings(COMPLETE_PROD_ENV)
        self.assertEqual(code, 0, stderr)
        self.assertIn('DEBUG=False', stdout)

    def test_debug_is_off(self):
        """The single most important assertion in this file."""
        _, stdout, _ = load_prod_settings(COMPLETE_PROD_ENV)
        self.assertIn('DEBUG=False', stdout)

    def test_allowed_hosts_is_not_a_wildcard(self):
        _, stdout, _ = load_prod_settings(COMPLETE_PROD_ENV)
        hosts_line = next(ln for ln in stdout.splitlines()
                          if ln.startswith('ALLOWED_HOSTS='))
        self.assertNotIn('*', hosts_line)
        self.assertIn('kukanjiten.com', hosts_line)

    def test_ssl_redirect_is_on(self):
        _, stdout, _ = load_prod_settings(COMPLETE_PROD_ENV)
        self.assertIn('SSL_REDIRECT=True', stdout)

    def test_missing_secret_key_refuses_to_start(self):
        code, _, stderr = load_prod_settings(
            COMPLETE_PROD_ENV, remove=['DJANGO_SECRET_KEY'])
        self.assertNotEqual(code, 0, 'prod started without a SECRET_KEY')
        self.assertIn('ImproperlyConfigured', stderr)
        self.assertIn('DJANGO_SECRET_KEY', stderr)

    def test_every_required_variable_is_actually_required(self):
        """One subprocess per variable. Slow, but this is the guarantee the
        whole stage exists to provide, and a variable that silently acquires a
        default is exactly the regression that matters."""
        for name in COMPLETE_PROD_ENV:
            with self.subTest(missing=name):
                code, stdout, stderr = load_prod_settings(
                    COMPLETE_PROD_ENV, remove=[name])
                self.assertNotEqual(
                    code, 0,
                    f'prod settings loaded without {name}:\n{stdout}')
                self.assertIn('ImproperlyConfigured', stderr)

    def test_no_settings_prod_star_import_remains(self):
        """PSN_TOKEN was a vestigial setting that only the old settings.py
        defined. Its absence is a cheap proxy for the star-import being gone."""
        _, stdout, _ = load_prod_settings(COMPLETE_PROD_ENV)
        self.assertIn('HAS_SETTINGS_PROD_FALLBACK=False', stdout)


class SettingsPackageTest(SimpleTestCase):
    """Structural checks that do not need a subprocess."""

    def test_dev_and_test_import_cleanly(self):
        import importlib
        for name in ['kukansite.settings.base', 'kukansite.settings.dev']:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))

    def test_base_defines_no_secret_key_or_debug(self):
        """base.py must not carry a default for either: a default is what let
        the old file fall back to development behaviour in production."""
        from kukansite.settings import base
        self.assertFalse(hasattr(base, 'SECRET_KEY'))
        self.assertFalse(hasattr(base, 'DEBUG'))

    def test_base_dir_points_at_the_repository_root(self):
        """base.py moved one directory deeper; BASE_DIR must not follow it."""
        from kukansite.settings import base
        self.assertTrue(os.path.isfile(os.path.join(base.BASE_DIR,
                                                    'manage.py')))
        self.assertTrue(os.path.isdir(os.path.join(base.BASE_DIR, 'kukan')))

    def test_the_log_directory_exists_after_importing_settings(self):
        """`logs/` is gitignored, so a fresh checkout and the staging container
        both start without it. The handler has delay=True, so the miss does not
        show at startup — it shows as a `--- Logging error ---` traceback per
        record, the first time anything logs, with requests still being served.

        Asserted against the handler's own filename rather than LOG_DIR, so
        that moving the log file without moving the makedirs fails here.
        """
        from django.conf import settings
        handler = settings.LOGGING['handlers']['default_file']
        self.assertTrue(
            os.path.isdir(os.path.dirname(handler['filename'])),
            f"{handler['filename']}'s directory does not exist; every log "
            f"record will raise FileNotFoundError")

    def test_settings_package_itself_defines_nothing(self):
        import kukansite.settings as pkg
        self.assertFalse(hasattr(pkg, 'INSTALLED_APPS'))
