from django.db import connection, transaction
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kukansite.settings")
import django
django.setup()

cursor = connection.cursor()

cursor.execute("vacuum")
transaction.commit()