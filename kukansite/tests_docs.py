"""Checks that the two deployment documents still describe this codebase.

`deploy/REHEARSAL.md` and `deploy/UPGRADE.md` are deliberately self-contained:
they repeat facts rather than cross-referencing, so that following one never
means opening another that may have drifted. The cost of that choice is that
the repeated facts can go stale silently, and a stale runbook is worse than no
runbook — it is read under time pressure, on the live box.

So the facts worth pinning are pinned here. This is not a spell-check; each
assertion below is something that, if it changed in the code and not in the
document, would send somebody down the wrong path during an upgrade.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import Resolver404, resolve

DEPLOY = pathlib.Path(settings.BASE_DIR) / 'deploy'
REHEARSAL = DEPLOY / 'REHEARSAL.md'
UPGRADE = DEPLOY / 'UPGRADE.md'


class BothDocumentsExistTest(SimpleTestCase):
    def test_both_are_present(self):
        self.assertTrue(REHEARSAL.is_file())
        self.assertTrue(UPGRADE.is_file())

    def test_neither_points_at_a_document_that_was_deleted(self):
        """They replaced STAGE7-CUTOVER.md and PROD-BOX-STAGING.md. A link to
        either is a link to nothing."""
        for doc in [REHEARSAL, UPGRADE]:
            text = doc.read_text()
            self.assertNotIn('STAGE7-CUTOVER', text, doc.name)
            self.assertNotIn('PROD-BOX-STAGING', text, doc.name)

    #: Paths the documents name precisely because this release removes them.
    DELETED_ON_PURPOSE = {'kukan/static/js/'}

    def test_every_repository_path_they_name_exists(self):
        root = pathlib.Path(settings.BASE_DIR)
        pattern = re.compile(
            r'`((?:deploy|kukansite|kukan|tempmon|bustime)/[\w./-]+'
            r'|Containerfile|pyproject\.toml|uv\.lock)`')
        for doc in [REHEARSAL, UPGRADE]:
            for ref in sorted(set(pattern.findall(doc.read_text()))):
                if ref in self.DELETED_ON_PURPOSE:
                    self.assertFalse(
                        (root / ref).exists(),
                        f'{ref} is listed as deleted but still exists; either '
                        f'the deletion was reverted or this entry is stale')
                    continue
                with self.subTest(doc=doc.name, path=ref):
                    self.assertTrue((root / ref).exists(),
                                    f'{doc.name} names {ref}, which does not exist')


class UrlsInTheDocumentsResolveTest(TestCase):
    """Every site URL the verification sections tell you to open.

    A renamed route would otherwise be found by whoever is working through the
    checklist at the point where the page 404s.
    """

    def paths(self, doc):
        text = doc.read_text()
        found = set(re.findall(r'`(/[\w/-]*/?)`', text))
        found |= set(re.findall(r'kukanjiten\.com(/[\w/-]+)', text))
        # Filesystem paths and server-served prefixes are not Django routes.
        return {p for p in found
                if not p.startswith(('/etc', '/home', '/srv', '/var', '/opt',
                                     '/data', '/static', '/.well-known',
                                     '/kukan/static'))
                and p not in ('/', '/login')}

    def test_urls_resolve(self):
        for doc in [REHEARSAL, UPGRADE]:
            for path in sorted(self.paths(doc)):
                with self.subTest(doc=doc.name, path=path):
                    try:
                        resolve(path)
                    except Resolver404:
                        self.fail(f'{doc.name} tells you to open {path}, '
                                  f'which does not resolve')

    def test_the_sensor_endpoint_is_quoted_with_its_trailing_slash(self):
        """`add_temp_point` is a hardware contract: the firmware has no retry
        buffer, so a reading it fails to deliver is gone. A runbook that has
        the URL wrong sends somebody looking for a fault that is not there."""
        text = UPGRADE.read_text()
        self.assertIn('/tempmon/add_temp_point/', text)
        # Only the URL form is constrained; `grep add_temp_point` in a log
        # command is prose and has no slash to get wrong.
        self.assertNotRegex(text, r'/tempmon/add_temp_point(?!/)')


class ManagementCommandsInTheDocumentsExistTest(SimpleTestCase):
    def test_every_manage_py_command_is_real(self):
        root = pathlib.Path(settings.BASE_DIR)
        real = {'migrate', 'collectstatic', 'check', 'test', 'runserver'}
        for app in ['kukan', 'utils_django', 'tempmon', 'bustime']:
            commands = root / app / 'management' / 'commands'
            if commands.is_dir():
                real |= {f.stem for f in commands.glob('*.py')
                         if not f.name.startswith('_')}

        for doc in [REHEARSAL, UPGRADE]:
            for command in sorted(set(re.findall(r'manage\.py (\w+)',
                                                 doc.read_text()))):
                with self.subTest(doc=doc.name, command=command):
                    self.assertIn(command, real,
                                  f'{doc.name} runs `manage.py {command}`, '
                                  f'which is not a command')


class UpgradeDocumentMatchesSettingsTest(SimpleTestCase):
    """The facts UPGRADE.md repeats out of `kukansite/settings/prod.py`."""

    def test_every_required_env_var_is_listed(self):
        """`prod.py` raises ImproperlyConfigured on a missing variable, so one
        left out of the document is a failed deploy at section 9."""
        prod = (pathlib.Path(settings.BASE_DIR)
                / 'kukansite' / 'settings' / 'prod.py').read_text()
        required = set(re.findall(r"env\('([A-Z_0-9]+)'", prod))
        self.assertTrue(required, 'found no env() calls to check against')

        text = UPGRADE.read_text()
        for name in sorted(required):
            with self.subTest(variable=name):
                # ANKI_AYUMI_USER and friends are covered by one `ANKI_*` row.
                if name.startswith('ANKI_'):
                    self.assertIn('ANKI_', text)
                    continue
                self.assertIn(name, text,
                              f'prod.py requires {name}; UPGRADE.md does not '
                              f'mention it')

    def test_the_cron_schedule_table_matches_cron_cfg(self):
        prod = (pathlib.Path(settings.BASE_DIR)
                / 'kukansite' / 'settings' / 'prod.py').read_text()
        block = prod[prod.index('CRON_CFG'):]
        schedules = re.findall(r"'schedule': '(\d+) (\d+)", block)
        self.assertTrue(schedules, 'found no CRON_CFG schedules')

        text = UPGRADE.read_text()
        for minute, hour in schedules:
            with self.subTest(schedule=f'{hour}:{minute}'):
                self.assertIn(f'{int(hour):02d}:{int(minute):02d}', text,
                              f'CRON_CFG runs a job at {hour}:{minute}; '
                              f'UPGRADE.md does not say so')


class RehearsalDocumentMatchesTheContainerTest(SimpleTestCase):
    """The facts REHEARSAL.md repeats out of the container definition."""

    def test_the_entrypoint_lines_it_quotes_are_the_ones_printed(self):
        """It reproduces the expected startup output. If the entrypoint gains
        or loses a check, the document stops matching what you see."""
        entrypoint = (DEPLOY / 'staging-entrypoint.sh').read_text()
        printed = re.findall(r"echo '(==> [^']+)'", entrypoint)
        self.assertTrue(printed, 'found no ==> lines in the entrypoint')

        text = REHEARSAL.read_text()
        for line in printed:
            with self.subTest(line=line):
                self.assertIn(line, text,
                              f'the entrypoint prints "{line}"; REHEARSAL.md '
                              f'does not show it')

    def test_the_anki_pin_it_quotes_is_the_real_one(self):
        """The whole reason the rehearsal runs on the production box."""
        pyproject = (pathlib.Path(settings.BASE_DIR)
                     / 'pyproject.toml').read_text()
        pin = re.search(r'anki==([\d.]+)', pyproject)
        self.assertIsNotNone(pin, 'no anki pin found in pyproject.toml')
        self.assertIn(f'anki=={pin.group(1)}', REHEARSAL.read_text())
        self.assertIn(pin.group(1), UPGRADE.read_text())

    def test_the_scrub_guard_paths_it_quotes_are_the_real_ones(self):
        scrub = (pathlib.Path(settings.BASE_DIR) / 'kukan' / 'management'
                 / 'commands' / 'scrub_local_db.py').read_text()
        markers = re.search(r'PROD_DB_MARKERS = \[(.*?)\]', scrub, re.S)
        self.assertIsNotNone(markers)
        text = REHEARSAL.read_text()
        for path in re.findall(r"'([^']+)'", markers.group(1)):
            with self.subTest(path=path):
                self.assertIn(path, text)
