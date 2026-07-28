"""Development settings — a laptop or the podman dev container.

Safe to run with no environment at all: every value here is a throwaway. The
credentials below are deliberately obvious dummies, so that a `manage.py`
command accidentally pointed at these settings cannot reach a real service.

Run with:  uv run manage.py <command>
(manage.py defaults DJANGO_SETTINGS_MODULE to this module.)

Real values, when you need them, come from a .env file that is *not* committed:

    uv run --env-file .env manage.py <command>
"""

from kukansite.env import env, env_bool, env_list
from kukansite.settings.base import *  # noqa: F403
from kukansite.settings.base import BASE_DIR  # noqa: F401  (re-export for clarity)

DEBUG = env_bool('DJANGO_DEBUG', True)

# Not a secret: development only, and it is in the repository. Production reads
# its key from the environment and refuses to start without one.
SECRET_KEY = env(
    'DJANGO_SECRET_KEY',
    'dev-only-insecure-key-do-not-use-anywhere-real')

ALLOWED_HOSTS = env_list(
    'DJANGO_ALLOWED_HOSTS',
    ['*', '192.168.12.10', '127.0.0.1', '0.0.0.0', 'localhost'])

INTERNAL_IPS = ['127.0.0.1']

# Dummy credentials. `__dummy__` is a sentinel tempmon checks for before
# attempting a PSN login at import time — do not replace it with ''.
DROPBOX_TOKEN = env('DROPBOX_TOKEN', 0)
TEMPMON_API_KEY = env('TEMPMON_API_KEY', '__dummy__')

ANKI_ACCOUNTS = {
    'Ayumi': {'user': 'name@dom.com', 'password': 'pwd', 'backup': True},
    'Fred': {'user': 'name@dom.com', 'password': 'pwd', 'backup': True},
    'Test2': {'user': 'fr_yjp-test@yahoo.co.jp', 'password': 'decktesting',
              'backup': False}
}

# Present so `manage.py set_cron` can be exercised locally. It only ever prints
# unless --exec is passed.
CRON_CFG = [
    {
        'schedule': '03 03  * * 0-6',
        'command': 'backup_db',
    },
    {
        'schedule': '04 04  * * 0-6',
        'command': 'sync_anki',
    },
]
