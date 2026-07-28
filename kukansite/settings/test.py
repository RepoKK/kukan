"""Test settings.

`manage.py test` selects this automatically (see manage.py).

Two things it does that dev cannot:

**Blocks the network.** Every outbound socket raises. The suite mocks all of
its HTTP — kanjipedia, goo, tobus.jp, Dropbox, PSN, AnkiWeb — so any connection
attempt means a mock was missed. Without this, such a test passes on a
developer's machine, passes slowly in CI, and fails on the day the remote site
changes or the runner has no egress. The two genuinely live tests
(`tempmon.tests.TestPsn`, `kukan.tests.TestDefinitionReal`) are skipped unless
their opt-in environment variable is set, and that variable also lifts this
block.

**Fast password hashing.** MD5 rather than PBKDF2. The suite creates users
constantly and PBKDF2 is deliberately slow.
"""

import os
import socket

from kukansite.settings.dev import *  # noqa: F403

# Deterministic and obviously fake.
SECRET_KEY = 'test-only-key'
DEBUG = False
ALLOWED_HOSTS = ['*', 'testserver']

# ~2s off the suite. Never use outside tests.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# The suite asserts against plain http:// URLs; a redirect middleware would
# turn every response into a 301.
SECURE_SSL_REDIRECT = False

DROPBOX_TOKEN = 'test-dropbox-token'
TEMPMON_API_KEY = 'test-api-key'


class NetworkBlockedInTests(RuntimeError):
    """Raised when a test tries to open a socket."""


# Opt-outs: the live contract tests set these to run against the real service.
_LIVE_TEST_VARS = ['psn_token', 'KUKAN_LIVE_WEB_TESTS']
_NETWORK_ALLOWED = any(os.environ.get(name) for name in _LIVE_TEST_VARS)


def _blocked_socket(*args, **kwargs):
    raise NetworkBlockedInTests(
        'A test tried to open a network connection. The suite is meant to be '
        'hermetic — mock the call instead. To run the live contract tests, '
        f'set one of {_LIVE_TEST_VARS}.')


if not _NETWORK_ALLOWED:
    # Patch the constructor rather than socket.socket itself: sqlite, the test
    # client and the multiprocessing runner all need the module to keep
    # working, and unix-domain sockets are used internally.
    _real_socket_init = socket.socket.__init__

    def _guarded_socket_init(self, family=socket.AF_INET, *args, **kwargs):
        if family in (socket.AF_INET, socket.AF_INET6):
            _blocked_socket()
        return _real_socket_init(self, family, *args, **kwargs)

    socket.socket.__init__ = _guarded_socket_init
    socket.create_connection = _blocked_socket
