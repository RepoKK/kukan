from django.db import connection, transaction

from utils_django.management_command import FBaseCommand


class Command(FBaseCommand):
    help = 'Optimize SQLite database'

    def handle_cmd(self, *args, **options):
        cursor = connection.cursor()

        cursor.execute('vacuum')
        transaction.commit()
