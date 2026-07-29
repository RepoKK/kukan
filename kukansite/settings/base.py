"""Settings shared by every environment.

This module holds nothing secret and nothing environment-specific. It must stay
importable with no environment variables set at all — `dev`, `prod` and `test`
each import it and then supply what they need.

There is deliberately no `DEBUG` and no `SECRET_KEY` here. Forgetting to set
either should be an error, not a silent default; that is the whole point of the
split (see kukansite/env.py for what it replaced).

Note this file is one level deeper than the old `kukansite/settings.py`, hence
the extra dirname() when computing BASE_DIR.
"""

import os

from django.contrib.messages import constants as message_constants

from kukansite.env import env

# .../kukan/kukansite/settings/base.py -> .../kukan
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.forms',
    'django_htmx',
    'kukan',
    'utils_django',
    'bustime',
    'tempmon'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Sets request.htmx; must come before anything that reads it below.
    'django_htmx.middleware.HtmxMiddleware',
    # Deny by default (Django 5.1). Every view requires a login unless it is
    # explicitly marked @login_not_required.
    #
    # Adopted because opting *in* per view had already failed twice, silently:
    # AjaxList.dispatch routed `?ajax=1` around LoginRequiredMixin and served
    # every list as JSON to anonymous callers, and PsnApiKeyUpdateView — the
    # form that sets the PlayStation npsso token — simply never had the mixin.
    # Both were live on kukanjiten.com. A view that forgets the mixin now fails
    # closed instead of open.
    #
    # Must come after AuthenticationMiddleware, which sets request.user.
    'django.contrib.auth.middleware.LoginRequiredMiddleware',
    # Must come after LoginRequiredMiddleware, to see the 302 it produces. An
    # htmx request that hits it unauthenticated would otherwise swap the login
    # page's HTML into whatever element issued the request, instead of
    # navigating the browser there.
    'kukan.middleware.HtmxLoginRedirectMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'kukansite.urls'

FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'kukansite.wsgi.application'

# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        # Overridable so that a *copy* of the production database can be
        # scrubbed without touching the working one:
        #
        #   cp ~/backup.sqlite3 deploy/staging-db.sqlite3
        #   KUKAN_DB_PATH=deploy/staging-db.sqlite3 \
        #       uv run manage.py scrub_local_db --yes-i-am-not-in-production
        #
        # Production leaves it unset and gets the path it always had.
        'NAME': env('KUKAN_DB_PATH', os.path.join(BASE_DIR, 'db.sqlite3')),
        # Concurrency. Under mod_wsgi the application was effectively a single
        # process serving one request at a time, so none of this was needed.
        # Gunicorn with `--threads 4` means four threads share one database
        # file, and stock SQLite answers a contended write with an immediate
        # "database is locked" rather than waiting.
        #
        #   journal_mode=WAL   readers stop blocking the writer and vice versa.
        #                      Persisted in the file, so it survives a restart.
        #   synchronous=NORMAL the pairing SQLite documents for WAL: still
        #                      crash-safe, without an fsync per commit.
        #   busy_timeout       wait up to 5s for a lock instead of failing at
        #                      once. Covers the nightly backup and sync_anki
        #                      jobs, which write from a separate process.
        #
        # transaction_mode IMMEDIATE takes the write lock when the transaction
        # opens rather than at its first write. Without it, two transactions
        # that both start read-only and then try to upgrade deadlock, and
        # SQLite cannot resolve that by waiting — one gets SQLITE_BUSY with no
        # safe retry. Requires Django 5.1+.
        'OPTIONS': {
            'init_command': (
                'PRAGMA journal_mode=WAL;'
                'PRAGMA synchronous=NORMAL;'
                'PRAGMA busy_timeout=5000;'
            ),
            'transaction_mode': 'IMMEDIATE',
        },
    }
}

# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation'
                '.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation'
                '.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation'
                '.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation'
                '.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/2.0/topics/i18n/

LANGUAGE_CODE = 'ja'

TIME_ZONE = 'Asia/Tokyo'

USE_I18N = True

# USE_L10N was removed in Django 5.0. Localized formatting has been
# unconditional since 4.0, so deleting the setting changes nothing.

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

CERT_ROOT = os.path.join(BASE_DIR, '.well-known')
CERT_URL = '/.well-known/'

TOP_DIR = os.path.dirname(BASE_DIR)
DB_BACKUP = os.path.join(TOP_DIR, 'db', '_backup')

ANKI_DB_DIR = os.path.join(TOP_DIR, 'db', 'Anki2')
ANKI_IMPORT_DIR = os.path.join(ANKI_DB_DIR, r'import')

FIXTURE_DIRS = [os.path.join(BASE_DIR, 'kukan', 'fixtures', 'Kanji')]

X_FRAME_OPTIONS = 'DENY'

# Redirect to home URL after login (Default redirects to /accounts/profile/)
LOGIN_URL = '/login'
LOGIN_REDIRECT_URL = '/'

# Bulma's notification colour modifiers, for ui/toasts.html. Django's default
# tags are debug/info/success/warning/error; Bulma has no "error" so that one
# maps to "danger" instead of falling through to an unstyled default.
MESSAGE_TAGS = {
    message_constants.DEBUG: 'is-dark',
    message_constants.INFO: 'is-info',
    message_constants.SUCCESS: 'is-success',
    message_constants.WARNING: 'is-warning',
    message_constants.ERROR: 'is-danger',
}

SERVER_EMAIL = 'kukanjiten'

# `logs/` is gitignored, so a fresh checkout does not have it — and neither did
# the staging container, whose build context excludes it. The handler below
# uses delay=True, so the miss does not surface at startup: it surfaces the
# first time anything logs, as a `--- Logging error ---` traceback per record,
# with the request itself still served. A 404 page that prints a stack trace to
# stderr and nothing to the log file is a bad way to find out.
#
# Created here rather than in the Containerfile because the exposure is not
# container-specific: deploying by cloning the repository somewhere new
# produces exactly the same missing directory on the production box.
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'default_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': os.path.join(LOG_DIR, 'info.log'),
            'delay': True,
            'encoding': 'utf-8',
            'when': 'W0',
            'backupCount': 5,
            'formatter': 'default_format',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
        }
    },
    'formatters': {
          'default_format': {
              'format': '{asctime}.{msecs:03.0f} {levelname:<8} '
                        '[{module}.{funcName}] {message}',
              'datefmt': '%Y%m%d %H:%M:%S',
              'style': '{',
          }
    },
    'root': {
        'handlers': ['default_file', 'mail_admins'],
        'level': 'DEBUG',
    },
    'loggers': {
        'kukan': {
            'handlers': ['default_file', 'mail_admins'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}
