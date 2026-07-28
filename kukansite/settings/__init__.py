"""Settings package.

Importing `kukansite.settings` directly is a mistake — it does not resolve to
any environment. Point DJANGO_SETTINGS_MODULE at one of:

    kukansite.settings.dev     laptop / dev container  (manage.py default)
    kukansite.settings.test    the test suite          (manage.py test)
    kukansite.settings.prod    kukanjiten.com

This file is intentionally empty of settings. It used to be the 234-line
`kukansite/settings.py` that ended by star-importing an optional
`settings_prod` and swallowing any ImportError; see kukansite/settings/prod.py
for why that was dangerous.
"""
