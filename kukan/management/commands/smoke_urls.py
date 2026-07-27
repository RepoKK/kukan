"""Cheap breadth-first check that every simple page still renders.

Walks the project URLconf, keeps the patterns that need no arguments, GETs
each one as a logged-in user and reports anything that is not a success or a
redirect. It is deliberately shallow: it proves the view imports, the template
compiles and the ORM query runs, which is exactly the class of breakage a
large template or dependency refresh introduces.

    python manage.py smoke_urls
    python manage.py smoke_urls --username fred --verbosity 2
"""
import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

logger = logging.getLogger(__name__)

# Endpoints that a bare GET cannot exercise meaningfully. Each one is listed
# with the reason it is skipped rather than silently dropped.
DEFAULT_SKIP = {
    'add_temp_point': 'sensor endpoint, POSTs a JSON body',
    'kukan:get_goo': 'ajax endpoint, needs a word and calls goo.ne.jp',
    'kukan:get_similar_word': 'ajax endpoint, needs a word parameter',
    'kukan:get_yomi': 'ajax endpoint, needs a kanji parameter',
    'kukan:set_yomi': 'ajax endpoint, POST only',
    'kukan:get_furigana': 'ajax endpoint, needs a sentence parameter',
    'kukan:yoji_anki': 'ajax endpoint, needs a yoji parameter',
    'bustime:get_time_to_next_hana': 'ajax endpoint, scrapes tobus.jp',
}


def iter_url_names(resolver, namespace=None):
    """Yield the fully-qualified name of every named pattern in the URLconf."""
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            ns = entry.namespace or namespace
            yield from iter_url_names(entry, ns)
        elif isinstance(entry, URLPattern) and entry.name:
            yield f'{namespace}:{entry.name}' if namespace else entry.name


class Command(BaseCommand):
    help = 'GET every no-argument URL as a logged-in user and report failures.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            help='User to log in as. Defaults to the first superuser.')
        parser.add_argument(
            '--skip', action='append', default=[], metavar='URL_NAME',
            help='Additional URL name to skip. May be repeated.')

    def handle(self, *args, **options):
        # Let a broken view come back as a 500 instead of blowing up the walk:
        # reporting every failing URL in one run is the whole point.
        client = Client(raise_request_exception=False)
        client.force_login(self.get_user(options['username']))

        skip = dict(DEFAULT_SKIP)
        skip.update({name: 'skipped on the command line'
                     for name in options['skip']})

        checked, failures, skipped = [], [], []
        for name in sorted(set(iter_url_names(get_resolver()))):
            if name.startswith('admin:'):
                continue
            try:
                url = reverse(name)
            except NoReverseMatch:
                # Needs arguments; out of scope for a no-fixture smoke test.
                continue
            if name in skip:
                skipped.append((name, url, skip[name]))
                continue

            status = client.get(url).status_code
            checked.append((name, url, status))
            if status >= 400:
                failures.append((name, url, status))

        self.report(checked, failures, skipped, options['verbosity'])
        if failures:
            raise CommandError(
                f'{len(failures)} of {len(checked)} URLs failed')

    def get_user(self, username):
        user_model = get_user_model()
        if username:
            try:
                return user_model.objects.get(
                    **{user_model.USERNAME_FIELD: username})
            except user_model.DoesNotExist:
                raise CommandError(f'No such user: {username}')
        user = user_model.objects.filter(is_superuser=True).first()
        if user is None:
            raise CommandError(
                'No superuser found; pass --username to choose an account.')
        return user

    def report(self, checked, failures, skipped, verbosity):
        if verbosity >= 2:
            for name, url, status in checked:
                self.stdout.write(f'{status}  {name:<40} {url}')
            for name, url, reason in skipped:
                self.stdout.write(f'skip {name:<40} {url}  ({reason})')

        for name, url, status in failures:
            self.stdout.write(self.style.ERROR(
                f'{status}  {name:<40} {url}'))

        summary = (f'{len(checked)} URLs checked, {len(failures)} failed, '
                   f'{len(skipped)} skipped')
        style = self.style.ERROR if failures else self.style.SUCCESS
        self.stdout.write(style(summary))
