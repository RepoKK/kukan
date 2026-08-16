"""Tests for `.gitignore`: its failure mode is silent, not loud.

An unanchored `static/` entry used to also match `kukan/static/`, the app's
static *source* directory, not just `STATIC_ROOT` (the collectstatic *output*
directory at the repo root) it was meant for. Every new file placed under
`kukan/static/` silently vanished from `git status` — discovered when the
Stage 10 vendored htmx/Alpine/Bulma files landed there and never showed up
staged. `git ls-files`/`git status` only warn about this for files that were
never tracked in the first place, which is exactly the case that matters, so
this is asserted against real `git check-ignore` output rather than by
parsing the file as text.

The same class of bug, from an unanchored `*db*`, previously ate
`scrub_local_db.py` entirely — it was never pushed despite months of commits
referencing it.
"""
import os
import subprocess

from django.test import SimpleTestCase

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_ignored(relative_path):
    result = subprocess.run(
        ['git', 'check-ignore', '--quiet', relative_path],
        cwd=REPO_ROOT, check=False)
    return result.returncode == 0


class GitignoreAnchoringTest(SimpleTestCase):
    def test_the_collectstatic_output_directory_is_ignored(self):
        self.assertTrue(is_ignored('static/some-collected-file.js'))

    def test_the_app_static_source_directory_is_not_ignored(self):
        self.assertFalse(is_ignored('kukan/static/vendor/anything.js'))
        self.assertFalse(is_ignored('kukan/static/js/anything.js'))

    def test_a_bare_directory_name_pattern_is_not_reintroduced(self):
        """The regression itself: `static/` with no leading slash matches
        that directory name at any depth, not just at the repo root."""
        with open(os.path.join(REPO_ROOT, '.gitignore'), encoding='utf-8') as f:
            lines = [ln.strip() for ln in f]
        self.assertNotIn('static/', lines)
        self.assertIn('/static/', lines)
