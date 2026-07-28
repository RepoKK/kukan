"""PlayStation Network access for tempmon.

This module exists to get three things out of `tempmon/views.py`:

**No work at import time.** The old code built a `PSN` object at module scope,
which meant importing the views ran a database query and a network login. With
no `db.sqlite3` present every management command logged
`OperationalError: no such table: tempmon_psnapikey`, caught and discarded by a
bare `except` labelled "bootstrap catch-up". It also made the module close to
untestable: the login had already happened before any test could patch it.
`get_psn()` builds the client on first use instead.

**A test seam.** `reset_psn()` replaces the process-wide client, so a test can
install a fake without patching PSNAWP internals.

**No unhandled failure path into `add_temp_point`.** The sensor firmware is not
in this repository and has no retry buffer: whatever a POST fails to deliver is
gone. Previously, if PSN was unreachable the exception propagated out of
`get_current_game()`, `add_temp_point` caught it at the top level, and the
temperature reading — which has nothing to do with PlayStation — was dropped.
Nothing here raises: an unreachable PSN costs the game attribution for those
minutes and nothing else.

On the rate limiter
-------------------
PSNAWP 3.x paces requests with `pyrate_limiter`, and its `try_acquire` call
takes the default `blocking=True, timeout=-1` — it waits indefinitely rather
than failing. The bucket is a SQLite file shared by every process on the box,
so the nightly jobs and the web process draw on the same allowance.

`add_temp_point` calls into here on every sensor POST. Measured from the
production database, the sensor posts every 32 seconds — about 2,700 calls a
day against an allowance of 300 per 15 minutes, so roughly a tenth of the
budget in steady state. The danger is not the steady state; it is a burst (a
device retry loop, a new game triggering three calls in one request) draining
the bucket, at which point every subsequent sensor POST blocks in the limiter
until the window rolls, and the device times out.

Two defences, both here rather than in the view:

* `PRESENCE_TTL` collapses repeated presence lookups. It is deliberately just
  *under* the 32-second sensor interval, so normal operation is unaffected and
  each reading still gets its own live lookup — a burst of retries is what
  collapses. The plan proposed 60s; that also works, but it would make every
  other reading inherit the previous one's game, and game attribution is the
  only thing this data is for.
* `FAILURE_COOLDOWN` stops a PSN outage from making every single sensor POST
  wait for a network timeout.
"""
import logging
import threading
import time

from django.db import OperationalError
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import (
    PSNAWPAuthenticationError,
    PSNAWPNotFoundError,
)
from psnawp_api.models.trophies.trophy_constants import PlatformType
from pyrate_limiter import Duration, Rate

from tempmon.models import PsGame, PsnApiKey

logger = logging.getLogger(__name__)

# The pk stored against a data point when no game is running, or when we could
# not find out. `PlaySession.get_time_per_game` and the graph view both filter
# it out, so it reads as "not attributed" rather than as a game.
NO_GAME = -1

# A title PSN would not name for us. Kept as a row so the session still
# attributes its time to *something* distinguishable.
UNKNOWN_GAME_NAME = '__UNKNOWN__'

# What `scrub_local_db` writes, and what `dev.py` ships. Not a token; a marker
# meaning "there is deliberately no PSN here".
DUMMY_TOKEN = '__dummy__'

# Stated explicitly rather than left to the library default, which is the same
# 300-requests-per-15-minutes figure expressed as 1 per 3 seconds. Writing it
# down means a future PSNAWP release cannot change our pacing silently.
PSN_RATE_LIMIT = Rate(300, Duration.MINUTE * 15)

# Seconds. See the module docstring; just under the 32s sensor interval.
PRESENCE_TTL = 25

# Seconds to stop calling PSN for after a failure.
FAILURE_COOLDOWN = 300

# Presence reports the platform as e.g. 'PS5'. PSNAWP 3.x requires a
# PlatformType for `game_title`, where 1.3.3 did not take one at all.
DEFAULT_PLATFORM = PlatformType.PS5


class PsnUnavailable(RuntimeError):
    """Raised inside this module when PSN cannot be reached.

    Never escapes `get_current_game()`.
    """


class PsnClient:
    """A logged-in PlayStation Network session.

    Constructing one performs a network login, so it is built lazily by
    `get_psn()` and kept for the life of the process.

    Thread-safe by design rather than by accident: Stage 7 runs gunicorn with
    four threads sharing one worker, so four sensor POSTs can be in here at
    once. The lock means they make one presence call between them instead of
    four.
    """

    is_available = True

    def __init__(self, npsso, presence_ttl=PRESENCE_TTL,
                 failure_cooldown=FAILURE_COOLDOWN):
        # PSNAWP 3.x replaced the `accept_language=` / `country=` arguments
        # with a headers dict, merged over its defaults. Japanese and JP are
        # the whole point: they are what makes get_details return 日本語 game
        # names rather than English ones.
        self.psnawp = PSNAWP(
            npsso,
            headers={'Accept-Language': 'ja', 'Country': 'JP'},
            rate_limit=PSN_RATE_LIMIT,
        )
        logger.info('Logged into PSN')

        self.client = self.psnawp.me()
        self.me = self.psnawp.user(account_id=self.client.account_id)

        self.presence_ttl = presence_ttl
        self.failure_cooldown = failure_cooldown

        self._lock = threading.Lock()
        self._presence = None
        self._presence_at = 0.0
        self._failed_at = 0.0

    # --- Presence ---------------------------------------------------------

    def _stale_presence(self, now):
        """The last successful answer, if it is worth serving.

        Bounded by `failure_cooldown` rather than served indefinitely: during
        an outage the console really might have been switched off, and going on
        attributing play time to the last known game for hours would invent
        data. Five minutes of a session credited to the wrong game is a much
        smaller lie than that.
        """
        if self._presence is None:
            return None
        if now - self._presence_at >= self.failure_cooldown:
            return None
        return self._presence

    def _fetch_presence(self):
        """The cached, cooled-down presence lookup. May raise."""
        now = time.monotonic()
        with self._lock:
            fresh = (self._presence is not None
                     and now - self._presence_at < self.presence_ttl)
            if fresh:
                return self._presence

            cooling_down = (self._failed_at
                            and now - self._failed_at < self.failure_cooldown)
            if cooling_down:
                # Deliberately do not call PSN: the point of the cooldown is
                # that every sensor POST during an outage would otherwise wait
                # for its own network timeout.
                stale = self._stale_presence(now)
                if stale is not None:
                    return stale
                raise PsnUnavailable(
                    f'PSN failed less than {self.failure_cooldown}s ago')

            try:
                self._presence = self.me.get_presence()
            except Exception:
                self._failed_at = now
                stale = self._stale_presence(now)
                if stale is not None:
                    return stale
                raise

            self._failed_at = 0.0
            self._presence_at = now
            return self._presence

    def get_current_game(self):
        """The pk of the game being played right now, or NO_GAME.

        Never raises. `add_temp_point` calls this for every reading the sensor
        sends, and a PSN problem must not cost a temperature reading.
        """
        try:
            return self._current_game()
        except Exception as e:
            logger.error(f'Could not determine the current game: {e}')
            return NO_GAME

    def _current_game(self):
        status = self._fetch_presence()['basicPresence']

        if status.get('availability') == 'unavailable':
            return NO_GAME
        if status.get('primaryPlatformInfo', {}).get('onlineStatus') != 'online':
            return NO_GAME

        try:
            title = status['gameTitleInfoList'][0]
            title_id = title['npTitleId']
        except (KeyError, IndexError):
            # Online, but sitting on the dashboard. IndexError is new here:
            # 1.3.3's version caught only KeyError, so an empty
            # gameTitleInfoList raised out of the view.
            return NO_GAME

        return self.get_game_pk(title_id, self.platform_of(title))

    @staticmethod
    def platform_of(title_info):
        """PlatformType from a presence entry's `format` (e.g. 'PS5').

        `PlatformType` defines a `_missing_` hook, so an unrecognised value
        does not raise — it comes back as `PlatformType.UNKNOWN`, which would
        be passed straight to `game_title`. Mapping it to a real platform
        instead means a console PSN describes in a way this code has not seen
        still gets its title looked up.
        """
        try:
            platform = PlatformType(title_info.get('format'))
        except ValueError:
            return DEFAULT_PLATFORM
        return DEFAULT_PLATFORM if platform is PlatformType.UNKNOWN else platform

    # --- Game titles ------------------------------------------------------

    def get_game_name_in_jp(self, title_id, platform=DEFAULT_PLATFORM):
        """The Japanese title.

        `GameTitle.get_details` in PSNAWP 3.x is exactly the catalog request
        1.3.3 had to be hand-built here, reaching through
        `psnawp._request_builder` and importing `BASE_PATH` / `API_PATH` from
        `psnawp_api.utils.endpoints` — private API on both counts, and the
        reason this was the riskiest part of the upgrade. It is now one call.
        """
        game = self.psnawp.game_title(
            title_id=title_id,
            platform=platform,
            account_id=self.client.account_id,
        )
        return game.get_details(country='JP', language='ja-JP')[0]['name']

    def get_game_pk(self, title_id, platform=DEFAULT_PLATFORM):
        try:
            return PsGame.objects.get(title_id=title_id).pk
        except PsGame.DoesNotExist:
            pass

        try:
            name = self.get_game_name_in_jp(title_id, platform)
        except PSNAWPNotFoundError:
            # PSNAWPNotFound in 1.3.3; renamed in 3.x. The row is still
            # created, so the session attributes its time to a stable pk
            # rather than dropping it.
            name = UNKNOWN_GAME_NAME

        return PsGame.objects.create(title_id=title_id, name=name).pk

    # --- Token ------------------------------------------------------------

    @property
    def refresh_token_days(self):
        """Days until the npsso token has to be replaced by hand.

        1.3.3 needed
        `psnawp._request_builder.authenticator._auth_properties['refresh_token_expires_in']`
        — two private attributes and a private dict. 3.x publishes it.
        """
        return self.psnawp.authenticator.refresh_token_expiration_in / 60 / 60 / 24


class NullPsnClient:
    """Stands in when there is no usable token.

    Exists so that callers never have to check for None. The old code kept a
    module-level `psn` that was sometimes an object and sometimes None, and
    every use site that forgot the difference turned a PSN problem into a lost
    temperature reading.
    """

    is_available = False

    def __init__(self, reason=''):
        self.reason = reason

    def get_current_game(self):
        return NO_GAME

    def get_game_pk(self, title_id, platform=DEFAULT_PLATFORM):
        return NO_GAME

    @property
    def refresh_token_days(self):
        return None


# --- Process-wide client ------------------------------------------------------
#
# One login per process, created on first use. `_lock` matters for the same
# reason it does inside PsnClient: gunicorn threads.

_client = None
_lock = threading.Lock()


def get_psn():
    """The process-wide PSN client, building it on first use.

    Always returns something with `get_current_game()`; a failure gives a
    `NullPsnClient`, not None.
    """
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = _build_client()
    return _client


def reset_psn(client=None):
    """Replace the process-wide client.

    `PsnApiKeyUpdateView` calls this after a new token is saved. Tests call it
    to install a fake, and with no argument to clear it.
    """
    global _client
    with _lock:
        _client = client


def _build_client():
    try:
        api_key = PsnApiKey.objects.first()
    except OperationalError as e:
        # No database yet. Used to be a bare module-level except during
        # import; now it can only happen if something asks for PSN before
        # migrate has run.
        logger.error(f'Cannot read the PSN token: {e}')
        return NullPsnClient('no database')

    token = api_key.code if api_key else None
    if not token or token == DUMMY_TOKEN:
        return NullPsnClient('no token configured')

    return build_client_from_token(token)


def build_client_from_token(token):
    """Log in, or return a NullPsnClient explaining why not.

    Separate from `_build_client` so that `PsnApiKeyForm` can validate a token
    the user has just typed without touching the process-wide client.
    """
    try:
        return PsnClient(token)
    except PSNAWPAuthenticationError as e:
        logger.error(f'Failed to login to PSN: {e}')
        return NullPsnClient(f'authentication failed: {e}')
    except Exception as e:
        logger.error(f'Failed to login to PSN: {e}')
        return NullPsnClient(str(e))
