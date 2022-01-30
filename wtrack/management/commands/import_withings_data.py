import arrow

from utils_django.management_command import FBaseCommand
from wtrack.comm_withings import CommWithings


class Command(FBaseCommand):
    help = 'Import Withings'
    default_back_days = 21
    today = arrow.get(arrow.utcnow().date())
    default_start = str(today.shift(days=-21).date())
    default_end = str(today.shift(days=1).date())

    def add_arguments(self, parser):
        parser.add_argument(
            '--start_date',
            dest='start_date',
            type=str,
            default=self.default_start,
            help=f'Start date for the import, inclusive. '
                 f'{self.default_back_days} days before today by default'
                 f' ({self.default_start}).',
        )
        parser.add_argument(
            '--end_date',
            dest='end_date',
            type=str,
            default=self.default_end,
            help=f'End date for the import, exclusive. '
                 f'Tomorrow by default ({self.default_end}).',
        )

    def handle_cmd(self, *args, **options):
        comm = CommWithings()
        try:
            comm.connect()
            comm.import_data(arrow.get(options['start_date']),
                             arrow.get(options['end_date']))
        except CommWithings.NotAuthorized:
            comm.authorize_request()
