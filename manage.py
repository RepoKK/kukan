#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    # `manage.py test` gets the test settings, which block outbound network and
    # use a fast password hasher. Selecting them here rather than asking every
    # caller for --settings means CI, a local run and an IDE all agree.
    default_settings = ("kukansite.settings.test" if 'test' in sys.argv[1:]
                        else "kukansite.settings.dev")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
