from utils_django.management_command import FBaseCommand
from utils_django.models import ManagementCommandRun


class Command(FBaseCommand):
    """
    Force the removal of the Management Command lock
    """
    help = 'Clear the Management Command lock'

    use_lock = False

    def handle_cmd(self, *args, **options):
        ManagementCommandRun.objects.all().delete()
