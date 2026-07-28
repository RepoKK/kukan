"""Reading required configuration from the environment.

No third-party library: the whole requirement is "fail loudly when a variable
is missing", and that is a dozen lines.

The loudness is the point. What this replaces was:

    try:
        from kukansite.settings_prod import *
    except ImportError:
        pass

with `DEBUG = True` and `ALLOWED_HOSTS = ['*']` checked in above it. Any
ImportError raised *inside* settings_prod.py — a typo, a missing module, a
renamed dependency — was swallowed by that `except`, and the site came up with
the development defaults instead: full Django debug pages, complete with stack
traces, settings and SQL, served to the internet.

Every function here raises rather than falling back. A missing variable in
production must stop the process, not silently downgrade it.
"""
import os

from django.core.exceptions import ImproperlyConfigured

# Sentinel so that `default=None` can mean "the default really is None".
_UNSET = object()

TRUE_VALUES = {'1', 'true', 'yes', 'on'}
FALSE_VALUES = {'0', 'false', 'no', 'off'}


def env(name, default=_UNSET):
    """Return the environment variable `name`.

    Raises ImproperlyConfigured if it is unset and no default was given.
    """
    try:
        return os.environ[name]
    except KeyError:
        if default is _UNSET:
            raise ImproperlyConfigured(
                f'The environment variable {name} is required but not set. '
                f'In production it is read from /etc/kukan/kukan.env; in '
                f'development, from the .env file via `uv run --env-file`.'
            ) from None
        return default


def env_bool(name, default=_UNSET):
    value = env(name, default)
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    raise ImproperlyConfigured(
        f'The environment variable {name} should be a boolean, got '
        f'{value!r}. Use one of {sorted(TRUE_VALUES | FALSE_VALUES)}.')


def env_int(name, default=_UNSET):
    value = env(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ImproperlyConfigured(
            f'The environment variable {name} should be an integer, got '
            f'{value!r}.') from None


def env_list(name, default=_UNSET, separator=','):
    """Comma-separated list, e.g. ALLOWED_HOSTS."""
    value = env(name, default)
    if isinstance(value, list):
        return value
    return [item.strip() for item in str(value).split(separator) if item.strip()]
