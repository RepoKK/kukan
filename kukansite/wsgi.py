"""
WSGI config for kukansite project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# Production default. Anything that is not the live site (the staging
# container, a local gunicorn) sets DJANGO_SETTINGS_MODULE explicitly.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kukansite.settings.prod")

application = get_wsgi_application()
