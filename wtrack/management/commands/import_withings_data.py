from utils_django.management_command import FBaseCommand
from wtrack.comm_withings import CommWithings


class Command(FBaseCommand):
    help = 'Import Withings'

    def handle_cmd(self, *args, **options):
        comm = CommWithings()
        try:
            comm.connect()
            comm.import_data()
        except CommWithings.NotAuthorized:
            comm.authorize_request()
