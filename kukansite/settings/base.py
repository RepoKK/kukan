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
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
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

SERVER_EMAIL = 'kukanjiten'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'default_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'info.log'),
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
