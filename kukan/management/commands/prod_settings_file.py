import os
from django.conf import settings
from utils_django.dropbox import upload, download
from utils_django.management_command import FBaseCommand


class Command(FBaseCommand):
    help = 'Upload or download the settings_prod.py to Dropbox'

    def add_arguments(self, parser):
        parser.add_argument(
            'direction',
            choices=['upload', 'download'],
            default='',
            help='Upload to Dropbox or Download from Dropbox',
        )

        parser.add_argument(
            '--token',
            default=settings.DROPBOX_TOKEN,
            help='Dropbox API token',
        )

    def handle_cmd(self, *args, **options):
        file_name = 'settings_prod.py'
        file_path = os.path.join(settings.BASE_DIR,
                                 'kukansite',
                                 file_name)
        dropbox_file = f'/Prod_Settings/{file_name}'
        if options['direction'] == 'upload':
            upload(file_path, dropbox_file, options['token'])
        else:
            download(dropbox_file, file_path)
