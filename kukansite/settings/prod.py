"""Production settings for kukanjiten.com.

Every secret is read from the environment and every one of them is required.
There are no fallbacks here on purpose: this module must fail to import rather
than come up misconfigured.

What this replaces
------------------
The old `kukansite/settings.py` ended with:

    try:
        from kukansite.settings_prod import *
    except ImportError:
        pass

above which sat `DEBUG = True` and `ALLOWED_HOSTS = ['*']`. Any ImportError
raised *inside* settings_prod.py — a typo, a missing module, a renamed
dependency — was caught by that bare `except` and the site silently came up
with development defaults: Django debug pages, with stack traces, settings and
SQL, served to the internet. This module cannot do that.

Where the environment comes from
--------------------------------
`/etc/kukan/kukan.env`, owned root:kukan mode 0640, loaded by both systemd and
cron. See deploy/kukan.env.example for the full list, and
`utils_django/management/commands/set_cron.py`, which sources the same file so
that the nightly jobs see the same configuration the web process does.
"""

from kukansite.env import env, env_list
from kukansite.settings.base import *  # noqa: F403

DEBUG = False

SECRET_KEY = env('DJANGO_SECRET_KEY')

# Key rotation, one deploy at a time:
#   1. Put the current key in DJANGO_SECRET_KEY_FALLBACKS, generate a new
#      DJANGO_SECRET_KEY, deploy. Existing sessions keep working because
#      Django verifies signatures against the fallbacks too.
#   2. On the next deploy, remove the fallback. Anything still signed with the
#      old key is then rejected.
#
# The key that was checked into this repository must be treated as burned: it
# is in the git history and in every clone. Rotate it on the first deploy of
# this stage and drop the fallback on the second.
SECRET_KEY_FALLBACKS = env_list('DJANGO_SECRET_KEY_FALLBACKS', [])

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS')

# Credentials for the nightly jobs and the sensor endpoint.
DROPBOX_TOKEN = env('DROPBOX_TOKEN')
TEMPMON_API_KEY = env('TEMPMON_API_KEY')

ANKI_ACCOUNTS = {
    'Ayumi': {
        'user': env('ANKI_AYUMI_USER'),
        'password': env('ANKI_AYUMI_PASSWORD'),
        'backup': True,
    },
    'Fred': {
        'user': env('ANKI_FRED_USER'),
        'password': env('ANKI_FRED_PASSWORD'),
        'backup': True,
    },
    'Test2': {
        'user': env('ANKI_TEST2_USER'),
        'password': env('ANKI_TEST2_PASSWORD'),
        'backup': False,
    },
}

# Security. The site is HTTPS-only behind Apache; without SSL redirect and
# secure cookies the session cookie can be sent in clear on a first request.
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

# Apache terminates TLS and proxies onward, so Django must be told the original
# scheme or it will redirect https -> http and loop.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CSRF_TRUSTED_ORIGINS = env_list(
    'DJANGO_CSRF_TRUSTED_ORIGINS', ['https://kukanjiten.com'])

# Cron. Paths that used to be hard-coded to /home/fred now come from the
# environment, so the same config works if the account or layout ever moves.
LETSENCRYPT_ROOT = env('LETSENCRYPT_ROOT', '/home/fred/letsencrypt')
WEBROOT = env('KUKAN_WEBROOT', '/home/fred/kukan/')

CRON_CFG = [
    {
        'schedule': '03 03  * * 0-6',
        'command': 'backup_db',
    },
    {
        'schedule': '04 04  * * 0-6',
        'command': 'sync_anki',
    },
    {
        'schedule': '23 01 * * *',
        'command': 'certbot renew --quiet',
        'non_django': True,
        'arguments': {
            'webroot': f'-w {WEBROOT}',
            'config-dir': f'{LETSENCRYPT_ROOT}/config',
            'work-dir': f'{LETSENCRYPT_ROOT}/work/',
            'logs-dir': f'{LETSENCRYPT_ROOT}/logs/',
            # Was 'sudo systemctl restart Apache.service'. The unit is
            # httpd.service on CentOS; the old name silently failed, so the
            # renewed certificate was not picked up until something else
            # restarted Apache.
            'post-hook': '"sudo systemctl restart httpd.service"',
        }
    },
]
