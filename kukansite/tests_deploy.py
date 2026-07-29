"""Tests for the deployment configuration under deploy/.

These read text files rather than exercising code, which is unusual, and worth
justifying. Stage 7 moves the application out of Apache (mod_wsgi, in-process)
and behind gunicorn (a proxy, over loopback). The failure modes of that change
do not live in Python:

* If the catch-all `ProxyPass /` is ordered above the `/.well-known` alias,
  Apache proxies certbot's http-01 challenge to Django, Django answers 404
  (`static()` in kukansite/urls.py is DEBUG-only and contributes nothing in
  production), and renewal fails at 01:23 every night with nobody watching
  until the certificate expires.
* If `RequestHeader set X-Forwarded-Proto https` is missing, prod.py's
  `SECURE_SSL_REDIRECT` sends the browser to https, Apache proxies it, Django
  sees plain http again, and every page on the site is a redirect loop.

Both are one-line mistakes with no test that would otherwise catch them, and
both are only observable in production. The staging container checks the
running behaviour (deploy/staging-entrypoint.sh); this file checks the text, so
the check still runs on a machine with no container runtime.

Parsing Apache configuration properly is out of scope — `httpd -t` does that,
and STAGE7-CUTOVER.md says to run it. What is asserted here is only ordering
and presence.
"""
import os
import re

from django.test import SimpleTestCase

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_DIR = os.path.join(REPO_ROOT, 'deploy')

# Both vhosts, because staging is only a rehearsal if it has the same shape as
# the thing it rehearses. A fix applied to one and not the other is exactly the
# drift these tests exist to prevent.
VHOSTS = ['kukanjiten-httpd.conf', 'staging-httpd.conf']


def read_deploy_file(name):
    with open(os.path.join(DEPLOY_DIR, name), encoding='utf-8') as f:
        return f.read()


def strip_comments(text):
    """Drop `#` comment lines.

    The comments in these files talk at length about ProxyPass ordering, so
    matching against the raw text would find the explanation of the bug rather
    than the directive that avoids it.
    """
    return '\n'.join(line for line in text.splitlines()
                     if not line.lstrip().startswith('#'))


def directive_line(text, pattern):
    """Index of the first line matching `pattern`, or None."""
    for index, line in enumerate(text.splitlines()):
        if re.search(pattern, line):
            return index
    return None


class ProxyOrderingTest(SimpleTestCase):
    """The certificate-losing bug, and its neighbours."""

    def setUp(self):
        self.configs = {name: strip_comments(read_deploy_file(name))
                        for name in VHOSTS}

    def test_catch_all_proxypass_is_present(self):
        """Guards the guard: if the catch-all is renamed or removed, every
        ordering assertion below would pass vacuously."""
        for name, text in self.configs.items():
            with self.subTest(config=name):
                self.assertIsNotNone(
                    directive_line(text, r'^\s*ProxyPass\s+/\s+http://'),
                    f'{name} has no catch-all ProxyPass to order against')

    def test_well_known_is_excluded_from_the_proxy(self):
        """`ProxyPass /.well-known/ !` — without it the Alias is unreachable
        however it is ordered."""
        for name, text in self.configs.items():
            with self.subTest(config=name):
                self.assertIsNotNone(
                    directive_line(text, r'^\s*ProxyPass\s+/\.well-known/\s+!'),
                    f'{name}: certbot\'s webroot is not excluded from the '
                    f'proxy. Renewal will fail silently.')

    def test_well_known_exclusion_comes_before_the_catch_all(self):
        """mod_proxy takes the first matching rule, so order is the whole
        mechanism."""
        for name, text in self.configs.items():
            with self.subTest(config=name):
                exclusion = directive_line(
                    text, r'^\s*ProxyPass\s+/\.well-known/\s+!')
                catch_all = directive_line(
                    text, r'^\s*ProxyPass\s+/\s+http://')
                self.assertLess(
                    exclusion, catch_all,
                    f'{name}: the /.well-known exclusion is below the '
                    f'catch-all ProxyPass, so it never matches. This is how '
                    f'the certificate gets lost during the cutover.')

    def test_static_is_excluded_and_ordered_before_the_catch_all(self):
        for name, text in self.configs.items():
            with self.subTest(config=name):
                exclusion = directive_line(
                    text, r'^\s*ProxyPass\s+/static/\s+!')
                self.assertIsNotNone(
                    exclusion, f'{name}: /static/ is not excluded from the '
                               f'proxy, so Django is being asked to serve it')
                catch_all = directive_line(
                    text, r'^\s*ProxyPass\s+/\s+http://')
                self.assertLess(exclusion, catch_all)

    def test_every_alias_has_a_matching_proxypass_exclusion(self):
        """The general form of the rule, so a *new* Alias added later cannot
        be silently shadowed the way /.well-known would have been."""
        for name, text in self.configs.items():
            aliased = re.findall(r'^\s*Alias\s+(\S+)', text, re.MULTILINE)
            excluded = re.findall(r'^\s*ProxyPass\s+(\S+)\s+!', text,
                                  re.MULTILINE)
            for path in aliased:
                with self.subTest(config=name, alias=path):
                    self.assertIn(
                        path, excluded,
                        f'{name}: Alias {path} has no `ProxyPass {path} !`, '
                        f'so the catch-all proxy swallows it.')


class AcmeChallengeTest(SimpleTestCase):
    """The http-01 challenge is served over plain HTTP, by definition.

    certbot fetches it in order to *obtain* a certificate, so it cannot be
    asked to present one first. Two ways to break that, both of which lose the
    certificate silently at 01:23 rather than at deploy time: serve the webroot
    only on the TLS vhost, or redirect it to https along with everything else.
    ProxyOrderingTest covers the third way (the catch-all proxy).
    """

    def setUp(self):
        self.configs = {name: strip_comments(read_deploy_file(name))
                        for name in VHOSTS}

    def test_a_plain_http_vhost_exists(self):
        for name, text in self.configs.items():
            with self.subTest(config=name):
                self.assertIsNotNone(
                    directive_line(text, r'^\s*<VirtualHost\s+\*:(80|8080)>'),
                    f'{name} has no plain-HTTP vhost, so there is nowhere for '
                    f'the ACME challenge to be served from')

    def test_the_redirect_to_https_excludes_the_challenge(self):
        """`^(?!/\\.well-known/)(.*)$` — without the lookahead, Let's Encrypt
        follows a 301 to a certificate that does not exist yet."""
        for name, text in self.configs.items():
            with self.subTest(config=name):
                redirect = directive_line(text, r'^\s*RedirectMatch')
                self.assertIsNotNone(
                    redirect, f'{name}: no RedirectMatch to https')
                line = text.splitlines()[redirect]
                self.assertIn(
                    r'(?!/\.well-known/)', line,
                    f'{name}: the http -> https redirect does not exclude the '
                    f'ACME challenge, so renewal follows it and fails')

    def test_the_challenge_is_aliased_before_the_redirect(self):
        for name, text in self.configs.items():
            with self.subTest(config=name):
                alias = directive_line(text, r'^\s*Alias\s+/\.well-known/')
                redirect = directive_line(text, r'^\s*RedirectMatch')
                self.assertLess(alias, redirect)


class ForwardedProtoTest(SimpleTestCase):
    """The redirect-loop bug."""

    def test_x_forwarded_proto_is_set(self):
        for name in VHOSTS:
            with self.subTest(config=name):
                text = strip_comments(read_deploy_file(name))
                self.assertIsNotNone(
                    directive_line(
                        text,
                        r'^\s*RequestHeader\s+set\s+X-Forwarded-Proto\s+"https"'),
                    f'{name}: X-Forwarded-Proto is not set. With '
                    f'SECURE_SSL_REDIRECT on, every page becomes a redirect '
                    f'loop.')

    def test_the_header_is_set_not_merely_defaulted(self):
        """`setifempty` would let a client supply its own X-Forwarded-Proto
        and tell Django a plain-http request arrived over TLS."""
        for name in VHOSTS:
            with self.subTest(config=name):
                text = strip_comments(read_deploy_file(name))
                self.assertIsNone(
                    directive_line(
                        text, r'^\s*RequestHeader\s+setifempty\s+X-Forwarded-Proto'),
                    f'{name}: X-Forwarded-Proto uses setifempty, which trusts '
                    f'a client-supplied value')

    def test_settings_agree_with_the_header_apache_sends(self):
        """The two halves of the contract are in different files and different
        languages; nothing but this test connects them."""
        text = strip_comments(read_deploy_file('kukanjiten-httpd.conf'))
        self.assertIsNotNone(
            directive_line(text, r'X-Forwarded-Proto'),
            'Apache does not send the header prod.py trusts')

        prod_source = read_deploy_file(
            os.path.join('..', 'kukansite', 'settings', 'prod.py'))
        self.assertIn(
            "SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')",
            prod_source,
            'prod.py does not read the header Apache sends')


class GunicornConfigTest(SimpleTestCase):
    """The worker sizing, which is load-bearing for SQLite."""

    def setUp(self):
        # Executed rather than parsed: it is a Python file, and reading the
        # values it actually produces is the point.
        # The real path as the filename, not a bare basename: coverage.py
        # tries to resolve whatever is given here and reports "No source for
        # code" against a file that does not exist at the repository root.
        path = os.path.join(DEPLOY_DIR, 'gunicorn.conf.py')
        self.namespace = {}
        exec(compile(read_deploy_file('gunicorn.conf.py'), path, 'exec'),
             self.namespace)

    def test_binds_to_loopback_only(self):
        """gunicorn has no TLS and trusts X-Forwarded-Proto. Reachable from
        outside the box, it would let anyone claim their request was HTTPS."""
        self.assertTrue(self.namespace['bind'].startswith('127.0.0.1:'),
                        self.namespace['bind'])

    def test_a_single_worker(self):
        """One writer for one SQLite file, and one resident Janome tokenizer.
        Raising this needs a database that tolerates concurrent writers."""
        self.assertEqual(self.namespace['workers'], 1)

    def test_concurrency_comes_from_threads(self):
        self.assertGreater(self.namespace['threads'], 1)
        self.assertEqual(self.namespace['worker_class'], 'gthread')

    def test_timeout_outlives_a_slow_request(self):
        """The default 30s is shorter than an Anki export."""
        self.assertGreaterEqual(self.namespace['timeout'], 120)

    def test_proxy_headers_are_only_trusted_from_loopback(self):
        self.assertEqual(self.namespace['forwarded_allow_ips'], '127.0.0.1')


class SqliteConcurrencyTest(SimpleTestCase):
    """WAL and busy_timeout, which threads make necessary."""

    # One test below opens a real connection to check the pragmas took effect,
    # rather than only that the setting says so.
    databases = {'default'}

    def test_wal_is_enabled(self):
        from django.conf import settings
        init = settings.DATABASES['default']['OPTIONS']['init_command']
        self.assertIn('journal_mode=WAL', init.replace(' ', ''))

    def test_busy_timeout_is_set(self):
        """Without it a contended write fails immediately rather than
        waiting — which is what four threads on one file will produce."""
        from django.conf import settings
        init = settings.DATABASES['default']['OPTIONS']['init_command']
        self.assertIn('busy_timeout', init)

    def test_transactions_take_the_write_lock_up_front(self):
        from django.conf import settings
        self.assertEqual(
            settings.DATABASES['default']['OPTIONS']['transaction_mode'],
            'IMMEDIATE')

    def test_the_pragmas_are_actually_applied_to_a_connection(self):
        """Asserting on the setting only proves the setting. Django splits
        init_command on ';' and runs each statement, so a malformed value
        would raise here and nowhere else."""
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA busy_timeout')
            self.assertEqual(cursor.fetchone()[0], 5000)


class StagingParityTest(SimpleTestCase):
    """Staging is only useful while it resembles production."""

    def test_both_use_the_same_gunicorn_config(self):
        """The entrypoint used to hard-code `--workers 3`, which quietly made
        staging a test of a configuration production would never run."""
        entrypoint = read_deploy_file('staging-entrypoint.sh')
        self.assertIn('deploy/gunicorn.conf.py', entrypoint)
        self.assertNotIn('--workers', entrypoint)

    def test_staging_runs_the_production_settings_module(self):
        """prod.py is the module with the security headers and the
        refuses-to-start behaviour. Running staging on dev.py would rehearse
        none of it."""
        entrypoint = read_deploy_file('staging-entrypoint.sh')
        self.assertIn('DJANGO_SETTINGS_MODULE=kukansite.settings.prod',
                      entrypoint)

    def test_staging_env_covers_everything_prod_requires(self):
        """If prod.py gains a required variable, staging stops starting. This
        turns that into a test failure instead of a container that exits."""
        from kukansite.tests_settings import COMPLETE_PROD_ENV

        staging_env = read_deploy_file('staging.env')
        defined = {line.split('=', 1)[0].strip()
                   for line in staging_env.splitlines()
                   if '=' in line and not line.lstrip().startswith('#')}
        missing = set(COMPLETE_PROD_ENV) - defined
        self.assertEqual(
            missing, set(),
            f'deploy/staging.env is missing {sorted(missing)}; the staging '
            f'container will fail to start')

    # Everything in staging.env that would be a secret in production. Host
    # names, origins and paths are not secrets and are excluded; these are.
    SECRET_BEARING = ['DJANGO_SECRET_KEY', 'DROPBOX_TOKEN', 'TEMPMON_API_KEY',
                      'ANKI_AYUMI_PASSWORD', 'ANKI_FRED_PASSWORD',
                      'ANKI_TEST2_PASSWORD', 'ANKI_AYUMI_USER',
                      'ANKI_FRED_USER', 'ANKI_TEST2_USER']

    def test_staging_env_holds_no_real_credentials(self):
        """staging.env is committed, so its secrets must stay worthless.

        The plausible accident is somebody debugging a staging failure by
        pasting a real value in and not taking it out again. Requiring the
        marker word makes that a failing test rather than a commit.
        """
        values = {}
        for line in read_deploy_file('staging.env').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, _, value = line.partition('=')
                values[key.strip()] = value.strip()

        for key in self.SECRET_BEARING:
            with self.subTest(variable=key):
                value = values.get(key, '')
                self.assertTrue(
                    'staging' in value or 'example.invalid' in value,
                    f'{key} in deploy/staging.env does not look like a '
                    f'placeholder. This file is committed.')

    def test_no_database_is_baked_into_the_image(self):
        """An image is an easy thing to hand to somebody, and the database
        carries password hashes, a live PSN token and live sessions. It arrives
        on a bind mount instead, so there is no version of this image that
        contains one — including the layers a `docker save` would keep after a
        later `rm`."""
        with open(os.path.join(REPO_ROOT, 'Containerfile'), encoding='utf-8') as f:
            containerfile = f.read()
        for line in containerfile.splitlines():
            if line.startswith('COPY'):
                with self.subTest(line=line):
                    self.assertNotIn('sqlite', line.lower())

    def test_bytecode_is_compiled_one_file_at_a_time(self):
        """UV_COMPILE_BYTECODE=1 uses every core, and janome cannot afford it.

        Its dictionary is Python source: 113 MB, including a 5 MB literal in
        sysdic/connections1.py that peaks at 865 MB resident to compile. Several
        of those at once took the production box to swap, and uv's 60s-per-file
        timeout fired. This is the fix, and it is a one-word regression.
        """
        with open(os.path.join(REPO_ROOT, 'Containerfile'), encoding='utf-8') as f:
            containerfile = f.read()
        # Instructions only. The comments above the compileall step name the
        # variable in order to explain why it is not set.
        instructions = '\n'.join(line for line in containerfile.splitlines()
                                 if not line.lstrip().startswith('#'))
        self.assertNotIn('UV_COMPILE_BYTECODE', instructions)
        self.assertIn('compileall -q -j 1', instructions)

    def test_the_image_removes_the_stock_listen_directives(self):
        """Two files declaring the same port is fatal: "Cannot define multiple
        Listeners on the same IP:port". staging-httpd.conf owns 8080 and 8443,
        so the stock `Listen 80` and mod_ssl's conf.d/ssl.conf have to go —
        rewriting them to the same ports is what broke the first run."""
        with open(os.path.join(REPO_ROOT, 'Containerfile'), encoding='utf-8') as f:
            instructions = '\n'.join(line for line in f.read().splitlines()
                                     if not line.lstrip().startswith('#'))
        self.assertIn('rm -f /etc/httpd/conf.d/ssl.conf', instructions)
        self.assertNotIn('Listen 8443', instructions)
        # And the build proves it rather than trusting this test.
        self.assertIn('httpd -t', instructions)

    def test_the_image_can_scrub_its_own_database(self):
        """The prod box has no development environment — no Python 3.12, no uv,
        no compiler — and installing one just to run a management command would
        be a change to the machine being tested. The image already has a
        virtualenv, so it does the scrubbing."""
        entrypoint = read_deploy_file('staging-entrypoint.sh')
        self.assertIn('scrub_local_db --yes-i-am-not-in-production', entrypoint)
        # Under dev settings: scrub_local_db refuses to run unless DEBUG is on,
        # and that guard is not one to work around.
        self.assertIn('DJANGO_SETTINGS_MODULE=kukansite.settings.dev', entrypoint)

    def test_staging_env_does_not_shadow_the_real_env_file(self):
        """A guard against the obvious catastrophe: staging.env is committed,
        /etc/kukan/kukan.env is not, and they must never be the same file."""
        self.assertNotIn('/etc/kukan/kukan.env',
                         read_deploy_file('staging-entrypoint.sh'))
