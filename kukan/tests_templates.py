"""Checks that run over every template in the project rather than a page.

Both of these started as an assertion on one page after a real bug, and both
turned out to be worth generalising -- the second one immediately found two
more instances the per-page version had no reason to look at.
"""
import pathlib
import re

from django.conf import settings
from django.test import TestCase

REPO_ROOT = pathlib.Path(settings.BASE_DIR)


def project_templates():
    """Every template this repository owns.

    Skips node_modules and the virtualenv: those are vendored, and this is
    about code review, not about third-party content.
    """
    for path in REPO_ROOT.rglob('*.html'):
        parts = set(path.parts)
        if parts & {'node_modules', '.venv', '.git'}:
            continue
        yield path


class TemplateCommentSyntaxTest(TestCase):
    def test_no_multi_line_hash_comments(self):
        """`{# ... #}` is single-line only.

        Django's lexer matches the comment token with a non-DOTALL regex, so
        a `{#` with its `#}` on a later line is not recognised as a comment
        at all: every line of it renders as literal text. It is silent --
        the page still loads, it just has an explanatory paragraph in the
        middle of it -- and it had happened three separate times before this
        test existed. `{% comment %}` spans lines; `{# #}` does not.
        """
        offenders = []
        for path in project_templates():
            for match in re.finditer(r'\{#(.*?)#\}', path.read_text(),
                                     re.DOTALL):
                if '\n' in match.group(1):
                    line = path.read_text()[:match.start()].count('\n') + 1
                    offenders.append(
                        f'{path.relative_to(REPO_ROOT)}:{line}')
        self.assertEqual(
            offenders, [],
            'multi-line {# #} comments render as page text; '
            'use {% comment %}{% endcomment %}')


class TemplateVendorTest(TestCase):
    def test_no_template_loads_a_third_party_cdn(self):
        """Everything the browser fetches comes from `static/vendor/`.

        Two chart pages used to pull from cdn.jsdelivr.net, one of them
        without a version in the URL at all. That is a third-party script
        with full DOM access on a logged-in page, changing without notice.
        """
        offenders = []
        for path in project_templates():
            text = path.read_text()
            for host in ['cdn.jsdelivr.net', 'cdnjs.cloudflare.com',
                         'unpkg.com', 'ajax.googleapis.com']:
                if host in text:
                    offenders.append(f'{path.relative_to(REPO_ROOT)}: {host}')
        self.assertEqual(offenders, [],
                         'vendor the file under kukan/static/vendor/ instead')
