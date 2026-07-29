"""Make a copy of the production database safe to develop against.

The usual way to get a realistic dev database is to restore last night's
Dropbox backup. That copy carries real password hashes, a live PSN npsso token
and live session cookies, and it then sits on a laptop or in a container image.
This command strips those.

    manage.py scrub_local_db --yes-i-am-not-in-production

It is destructive and deliberately awkward to run. Three independent guards
have to pass:

1. ``DEBUG`` must be True.
2. The confirmation flag must be given in full.
3. The database must not be the production file (see PROD_DB_MARKERS).

Anything it cannot verify, it refuses. A scrubber that runs against prod is
worse than no scrubber, so the failure mode is always "do nothing".
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

logger = logging.getLogger(__name__)

CONFIRM_FLAG = '--yes-i-am-not-in-production'

# Path fragments that indicate the live database. Deliberately broad.
PROD_DB_MARKERS = ['/home/fred/kukan', '/srv/kukan', '/var/www']

DEV_PASSWORD = 'dev'


class Command(BaseCommand):
    help = ('Strip credentials and sessions from a local copy of the prod '
            'database. Refuses to run unless DEBUG is on.')

    def create_parser(self, prog_name, subcommand, **kwargs):
        # argparse accepts any unambiguous prefix by default, which would let
        # `--yes` stand in for the confirmation flag. The flag is long on
        # purpose; abbreviating it defeats that.
        return super().create_parser(prog_name, subcommand,
                                     allow_abbrev=False, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument(
            CONFIRM_FLAG, action='store_true', dest='confirmed',
            help='Required. Confirms this is not the production database.')
        parser.add_argument(
            '--password', default=DEV_PASSWORD,
            help=f'Password to set on every account (default: {DEV_PASSWORD})')

    def handle(self, *args, **options):
        self.check_safe_to_run(options['confirmed'])

        with transaction.atomic():
            names = self.reset_passwords(options['password'])
            keys = self.blank_psn_token()
            sessions = self.truncate_sessions()

        self.stdout.write(self.style.SUCCESS(
            f'Scrubbed: {len(names)} password(s) reset to '
            f'"{options["password"]}", {keys} PSN token(s) blanked, '
            f'{sessions} session(s) deleted.'))

        # Name them. The scrubbed copy exists to be logged into, and the
        # accounts in it are whatever production happens to have — not
        # necessarily the shell user's name, and not necessarily a superuser.
        # Printing them here saves a round trip through sqlite3 to find out
        # what the password that was just set actually belongs to.
        if names:
            self.stdout.write('Accounts: ' + ', '.join(
                f'{name}{"*" if superuser else ""}' for name, superuser in names))
            if not any(superuser for _, superuser in names):
                self.stdout.write(self.style.WARNING(
                    'No superuser among them. `manage.py smoke_urls` defaults '
                    'to the first superuser and will need --username.'))
            else:
                self.stdout.write('(* = superuser)')

    def check_safe_to_run(self, confirmed):
        if not settings.DEBUG:
            raise CommandError(
                'DEBUG is False. This command only runs on a development '
                'database and will not touch a production one.')

        if not confirmed:
            raise CommandError(
                f'This rewrites every password in the database. Re-run as:\n'
                f'    manage.py scrub_local_db {CONFIRM_FLAG}')

        db_path = str(settings.DATABASES['default']['NAME'])
        for marker in PROD_DB_MARKERS:
            if marker in db_path:
                raise CommandError(
                    f'Database path {db_path!r} contains {marker!r}, which '
                    f'looks like the production location. Refusing.')

    def reset_passwords(self, password):
        """Every account gets the same known password.

        `set_password` is used rather than a bulk UPDATE so the hash is
        produced by the configured hasher — a hand-written hash would stop
        working the moment PASSWORD_HASHERS changes.
        """
        user_model = get_user_model()
        users = list(user_model.objects.all())
        for user in users:
            user.set_password(password)
        user_model.objects.bulk_update(users, ['password'])
        return [(user.get_username(), user.is_superuser) for user in users]

    def blank_psn_token(self):
        """The npsso token is a live credential to the user's PSN account.

        Reset to the '__dummy__' sentinel rather than the empty string:
        `tempmon.views` compares against that value to decide whether to
        attempt a login at import time, so a blank would make it try.
        """
        from tempmon.models import PsnApiKey

        return PsnApiKey.objects.update(code='__dummy__')

    def truncate_sessions(self):
        """Session rows are live login cookies for whoever was signed in."""
        from django.contrib.sessions.models import Session

        count = Session.objects.count()
        Session.objects.all().delete()
        return count

    @staticmethod
    def vacuum():
        """Reclaim the space freed above so the scrubbed copy is not larger
        than it needs to be in a container image."""
        with connection.cursor() as cursor:
            cursor.execute('VACUUM')
