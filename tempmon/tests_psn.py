"""Tests for `tempmon.psn`.

These replace the `TestPsnWrapper` block that lived in `tests_views.py` before
Stage 8. That block existed as a porting checklist: it mocked every private
PSNAWP attribute the old `PSN` class reached for — `psnawp._request_builder`,
`BASE_PATH`, `API_PATH` from `psnawp_api.utils.endpoints`,
`authenticator._auth_properties['refresh_token_expires_in']` — so that the
extent of the dependency on unpublished API was written down somewhere.

All of it is gone in 3.0.3. What replaced it is public, so the tests below can
assert on behaviour instead of on internals, and the useful ones are now the
ones about *not* calling PSN: the cache, the failure cooldown, and the promise
that `get_current_game()` never raises.

That last one is the point of the module. The sensor firmware is not in this
repository and has no retry buffer, so a temperature reading that
`add_temp_point` fails to store is gone for good — and before this stage, an
unreachable PlayStation Network was enough to lose one.
"""
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from psnawp_api.core.psnawp_exceptions import (
    PSNAWPAuthenticationError,
    PSNAWPNotFoundError,
)
from psnawp_api.models.trophies.trophy_constants import PlatformType
from pyrate_limiter import Rate

from tempmon import psn as psn_module
from tempmon.models import PsGame, PsnApiKey
from tempmon.psn import (
    NO_GAME,
    UNKNOWN_GAME_NAME,
    NullPsnClient,
    PsnClient,
    get_psn,
    reset_psn,
)


def presence(availability='availableToPlay', online_status='online',
             titles=None):
    """A `get_presence()` payload, in the shape PSN actually returns."""
    basic = {'availability': availability,
             'primaryPlatformInfo': {'onlineStatus': online_status}}
    if titles is not None:
        basic['gameTitleInfoList'] = titles
    return {'basicPresence': basic}


PLAYING = presence(titles=[{'npTitleId': 'PPSA01', 'format': 'PS5'}])


class PsnClientTestCase(TestCase):
    """Base: a PsnClient over a mocked PSNAWP, with the global left alone."""

    def setUp(self):
        patcher = patch('tempmon.psn.PSNAWP')
        self.psnawp_cls = patcher.start()
        self.addCleanup(patcher.stop)

        self.psnawp = self.psnawp_cls.return_value
        self.psnawp.me.return_value.account_id = 'acct-1'
        self.user = self.psnawp.user.return_value

        # The process-wide client is global state; never let a test leak one.
        self.addCleanup(reset_psn)

    def make_client(self, **kwargs):
        return PsnClient('token', **kwargs)

    def set_presence(self, payload):
        self.user.get_presence.return_value = payload


class ConstructionTest(PsnClientTestCase):

    def test_requests_japanese_titles(self):
        """3.0.3 replaced `accept_language=` / `country=` with a headers dict.

        Getting this wrong is not a crash: game names silently come back in
        English and get written into PsGame that way, permanently.
        """
        self.make_client()
        _, kwargs = self.psnawp_cls.call_args
        self.assertEqual(kwargs['headers'],
                         {'Accept-Language': 'ja', 'Country': 'JP'})

    def test_the_token_is_the_first_argument(self):
        self.make_client()
        args, _ = self.psnawp_cls.call_args
        self.assertEqual(args[0], 'token')

    def test_the_rate_limit_is_stated_explicitly(self):
        """Left implicit, our pacing would be whatever a future PSNAWP release
        decides it should be."""
        self.make_client()
        _, kwargs = self.psnawp_cls.call_args
        self.assertIsInstance(kwargs['rate_limit'], Rate)

    def test_the_rate_limit_matches_psn_guidance(self):
        self.make_client()
        rate = self.psnawp_cls.call_args[1]['rate_limit']
        self.assertEqual(rate.limit, 300)
        self.assertEqual(rate.interval, 15 * 60 * 1000)  # milliseconds

    def test_refresh_token_days_comes_from_the_public_authenticator(self):
        """Was `psnawp._request_builder.authenticator._auth_properties[...]`."""
        self.psnawp.authenticator.refresh_token_expiration_in = 60 * 60 * 24 * 30
        self.assertAlmostEqual(self.make_client().refresh_token_days, 30)


class CurrentGameTest(PsnClientTestCase):
    """The four branches of `get_current_game`, plus the one 1.3.3 missed."""

    def test_offline_console(self):
        self.set_presence(presence(availability='unavailable'))
        self.assertEqual(self.make_client().get_current_game(), NO_GAME)

    def test_online_status_not_online(self):
        self.set_presence(presence(online_status='offline'))
        self.assertEqual(self.make_client().get_current_game(), NO_GAME)

    def test_online_but_on_the_dashboard(self):
        """No gameTitleInfoList key at all."""
        self.set_presence(presence())
        self.assertEqual(self.make_client().get_current_game(), NO_GAME)

    def test_an_empty_title_list(self):
        """1.3.3 caught only KeyError here, so an empty list raised IndexError
        out of the view and `add_temp_point` lost the reading."""
        self.set_presence(presence(titles=[]))
        self.assertEqual(self.make_client().get_current_game(), NO_GAME)

    def test_playing_a_known_game(self):
        game = PsGame.objects.create(title_id='PPSA01', name='Known Game')
        self.set_presence(PLAYING)
        self.assertEqual(self.make_client().get_current_game(), game.pk)


class GameLookupTest(PsnClientTestCase):

    def test_an_existing_row_is_reused(self):
        game = PsGame.objects.create(title_id='PPSA01', name='Known Game')
        client = self.make_client()
        self.assertEqual(client.get_game_pk('PPSA01'), game.pk)
        self.assertEqual(PsGame.objects.count(), 1)

    def test_a_known_title_costs_no_network_call(self):
        PsGame.objects.create(title_id='PPSA01', name='Known Game')
        self.make_client().get_game_pk('PPSA01')
        self.psnawp.game_title.assert_not_called()

    def test_a_new_title_is_stored_with_its_japanese_name(self):
        self.psnawp.game_title.return_value.get_details.return_value = [
            {'name': 'ゲーム名'}]
        pk = self.make_client().get_game_pk('PPSA01')
        self.assertEqual(PsGame.objects.get(pk=pk).name, 'ゲーム名')

    def test_the_details_call_asks_for_japanese(self):
        """`get_details` defaults to the authenticator's headers, which we do
        set — but the old code passed these explicitly and there is no reason
        to make the name depend on two things instead of one."""
        self.psnawp.game_title.return_value.get_details.return_value = [
            {'name': 'ゲーム名'}]
        self.make_client().get_game_pk('PPSA01')
        self.psnawp.game_title.return_value.get_details.assert_called_once_with(
            country='JP', language='ja-JP')

    def test_platform_is_passed_through(self):
        """New in 3.0.3: `game_title` takes a required PlatformType."""
        self.psnawp.game_title.return_value.get_details.return_value = [
            {'name': 'ゲーム名'}]
        self.make_client().get_game_pk('PPSA01', PlatformType.PS4)
        self.assertEqual(
            self.psnawp.game_title.call_args[1]['platform'], PlatformType.PS4)

    def test_platform_is_read_from_the_presence_payload(self):
        self.psnawp.game_title.return_value.get_details.return_value = [
            {'name': 'ゲーム名'}]
        self.set_presence(
            presence(titles=[{'npTitleId': 'PPSA01', 'format': 'PS4'}]))
        self.make_client().get_current_game()
        self.assertEqual(
            self.psnawp.game_title.call_args[1]['platform'], PlatformType.PS4)

    def test_an_unrecognised_platform_falls_back(self):
        self.assertEqual(PsnClient.platform_of({'format': 'PS7'}),
                         psn_module.DEFAULT_PLATFORM)

    def test_a_missing_platform_falls_back(self):
        self.assertEqual(PsnClient.platform_of({}),
                         psn_module.DEFAULT_PLATFORM)

    def test_an_unnameable_title_still_gets_a_row(self):
        """PSNAWPNotFound became PSNAWPNotFoundError in 3.x. The row matters:
        without it the session cannot attribute that time to anything."""
        self.psnawp.game_title.side_effect = PSNAWPNotFoundError('nope')
        pk = self.make_client().get_game_pk('PPSA-UNKNOWN')
        self.assertEqual(PsGame.objects.get(pk=pk).name, UNKNOWN_GAME_NAME)


class PresenceCacheTest(PsnClientTestCase):
    """The rate-limiter defence.

    PSNAWP's `try_acquire` blocks indefinitely by default. Draining the bucket
    does not raise, it *stalls* — and every stalled call is a sensor POST the
    device is waiting on.
    """

    def test_a_second_call_inside_the_ttl_does_not_hit_psn(self):
        self.set_presence(presence(availability='unavailable'))
        client = self.make_client(presence_ttl=60)
        client.get_current_game()
        client.get_current_game()
        self.user.get_presence.assert_called_once()

    def test_the_cache_expires(self):
        self.set_presence(presence(availability='unavailable'))
        client = self.make_client(presence_ttl=0)
        client.get_current_game()
        client.get_current_game()
        self.assertEqual(self.user.get_presence.call_count, 2)

    def test_the_default_ttl_is_under_the_sensor_interval(self):
        """Measured from the production database, the sensor posts every 32s.

        The cache is there to absorb bursts, not to make ordinary readings
        inherit the previous one's game — that would blur exactly the thing
        this data is collected for.
        """
        self.assertLess(psn_module.PRESENCE_TTL, 32)

    def test_a_cached_answer_is_still_correct(self):
        game = PsGame.objects.create(title_id='PPSA01', name='Known Game')
        self.set_presence(PLAYING)
        client = self.make_client(presence_ttl=60)
        self.assertEqual(client.get_current_game(), game.pk)
        self.assertEqual(client.get_current_game(), game.pk)


class FailureHandlingTest(PsnClientTestCase):
    """Nothing PSN does may cost a temperature reading."""

    def test_a_network_failure_returns_no_game_rather_than_raising(self):
        self.user.get_presence.side_effect = OSError('network is down')
        self.assertEqual(self.make_client().get_current_game(), NO_GAME)

    def test_an_unexpected_payload_shape_returns_no_game(self):
        """PSN changing its JSON must degrade, not break the sensor."""
        self.set_presence({})
        self.assertEqual(self.make_client().get_current_game(), NO_GAME)

    def test_a_failure_in_the_title_lookup_returns_no_game(self):
        self.set_presence(PLAYING)
        self.psnawp.game_title.side_effect = OSError('network is down')
        self.assertEqual(self.make_client().get_current_game(), NO_GAME)

    def test_psn_is_not_called_again_during_the_cooldown(self):
        """An outage must not make every sensor POST pay a network timeout."""
        self.user.get_presence.side_effect = OSError('network is down')
        client = self.make_client(presence_ttl=0, failure_cooldown=300)
        client.get_current_game()
        client.get_current_game()
        client.get_current_game()
        self.user.get_presence.assert_called_once()

    def test_the_last_known_answer_is_served_during_the_cooldown(self):
        game = PsGame.objects.create(title_id='PPSA01', name='Known Game')
        self.set_presence(PLAYING)
        client = self.make_client(presence_ttl=0, failure_cooldown=300)
        self.assertEqual(client.get_current_game(), game.pk)

        self.user.get_presence.side_effect = OSError('network is down')
        self.assertEqual(client.get_current_game(), game.pk)
        self.assertEqual(client.get_current_game(), game.pk)
        self.assertEqual(self.user.get_presence.call_count, 2)

    def test_a_stale_answer_is_not_served_forever(self):
        """An outage lasting longer than the cooldown means we genuinely do
        not know, and the console may simply have been switched off. Going on
        crediting play time to the last known game would invent data."""
        game = PsGame.objects.create(title_id='PPSA01', name='Known Game')
        self.set_presence(PLAYING)
        client = self.make_client(presence_ttl=0, failure_cooldown=0)
        self.assertEqual(client.get_current_game(), game.pk)

        self.user.get_presence.side_effect = OSError('network is down')
        self.assertEqual(client.get_current_game(), NO_GAME)

    def test_psn_is_tried_again_after_the_cooldown(self):
        self.user.get_presence.side_effect = OSError('network is down')
        client = self.make_client(presence_ttl=0, failure_cooldown=0)
        client.get_current_game()
        client.get_current_game()
        self.assertEqual(self.user.get_presence.call_count, 2)

    def test_recovery_clears_the_cooldown(self):
        client = self.make_client(presence_ttl=0, failure_cooldown=0)
        self.user.get_presence.side_effect = OSError('down')
        client.get_current_game()
        self.user.get_presence.side_effect = None
        self.set_presence(presence(availability='unavailable'))
        client.get_current_game()
        self.assertEqual(client._failed_at, 0.0)


class NullClientTest(SimpleTestCase):
    """The stand-in, so no caller ever has to check for None."""

    def test_reports_itself_unavailable(self):
        self.assertFalse(NullPsnClient().is_available)

    def test_a_real_client_reports_itself_available(self):
        self.assertTrue(PsnClient.is_available)

    def test_current_game_is_no_game(self):
        self.assertEqual(NullPsnClient().get_current_game(), NO_GAME)

    def test_game_pk_is_no_game(self):
        self.assertEqual(NullPsnClient().get_game_pk('PPSA01'), NO_GAME)

    def test_it_has_no_token_expiry(self):
        self.assertIsNone(NullPsnClient().refresh_token_days)

    def test_it_has_the_same_surface_as_the_real_client(self):
        """Guards the guard: if PsnClient grows a method, the null client has
        to grow it too, or a PSN outage turns into an AttributeError."""
        for name in ['is_available', 'get_current_game', 'get_game_pk',
                     'refresh_token_days']:
            with self.subTest(attribute=name):
                self.assertTrue(hasattr(NullPsnClient, name))


class ProcessWideClientTest(TestCase):
    """`get_psn()` / `reset_psn()` — the lazy global that replaced import-time
    construction."""

    def setUp(self):
        reset_psn()
        self.addCleanup(reset_psn)

    def test_a_dummy_token_gives_a_null_client(self):
        """`__dummy__` is what the migration seeds and what scrub_local_db
        writes. It means "there is deliberately no PSN here"."""
        self.assertIsInstance(get_psn(), NullPsnClient)

    def test_an_empty_token_gives_a_null_client(self):
        PsnApiKey.objects.update(code='')
        self.assertIsInstance(get_psn(), NullPsnClient)

    def test_no_row_at_all_gives_a_null_client(self):
        PsnApiKey.objects.all().delete()
        self.assertIsInstance(get_psn(), NullPsnClient)

    @patch('tempmon.psn.PSNAWP')
    def test_a_real_token_gives_a_real_client(self, psnawp_cls):
        psnawp_cls.return_value.me.return_value.account_id = 'acct-1'
        PsnApiKey.objects.update(code='a-real-looking-token')
        self.assertIsInstance(get_psn(), PsnClient)

    @patch('tempmon.psn.PSNAWP')
    def test_the_client_is_built_once(self, psnawp_cls):
        psnawp_cls.return_value.me.return_value.account_id = 'acct-1'
        PsnApiKey.objects.update(code='a-real-looking-token')
        get_psn()
        get_psn()
        get_psn()
        psnawp_cls.assert_called_once()

    @patch('tempmon.psn.PSNAWP')
    def test_a_failed_login_gives_a_null_client_not_an_exception(
            self, psnawp_cls):
        """An expired npsso token must leave the site usable. It expires every
        couple of months, so this is the normal case, not the rare one."""
        psnawp_cls.side_effect = PSNAWPAuthenticationError('expired')
        PsnApiKey.objects.update(code='an-expired-token')
        self.assertIsInstance(get_psn(), NullPsnClient)

    @patch('tempmon.psn.PSNAWP')
    def test_a_failed_login_is_not_retried_on_every_call(self, psnawp_cls):
        psnawp_cls.side_effect = PSNAWPAuthenticationError('expired')
        PsnApiKey.objects.update(code='an-expired-token')
        get_psn()
        get_psn()
        psnawp_cls.assert_called_once()

    def test_reset_psn_installs_a_given_client(self):
        fake = MagicMock()
        reset_psn(fake)
        self.assertIs(get_psn(), fake)

    def test_reset_psn_with_no_argument_clears(self):
        reset_psn(MagicMock())
        reset_psn()
        self.assertIsInstance(get_psn(), NullPsnClient)


class NoWorkAtImportTimeTest(SimpleTestCase):
    """The reason this module exists.

    `tempmon/views.py` used to build a PSN object at module scope, so importing
    it ran a database query and a network login. Every management command on a
    machine with no db.sqlite3 logged
    `OperationalError: no such table: tempmon_psnapikey`, and no test could
    patch the login because it had already happened.
    """

    def test_importing_the_module_does_not_log_in(self):
        import importlib

        with patch('psnawp_api.PSNAWP') as psnawp_cls:
            importlib.reload(psn_module)
            psnawp_cls.assert_not_called()
        # Reloading rebinds the module's globals; put the real one back so the
        # rest of the suite is not testing a half-reloaded module.
        importlib.reload(psn_module)

    def test_importing_the_views_does_not_log_in(self):
        import importlib

        from tempmon import views

        with patch('tempmon.psn.PSNAWP') as psnawp_cls:
            importlib.reload(views)
            psnawp_cls.assert_not_called()

    def test_the_module_holds_no_client_until_asked(self):
        reset_psn()
        self.addCleanup(reset_psn)
        self.assertIsNone(psn_module._client)


class ThreadSafetyTest(PsnClientTestCase):
    """Stage 7 runs gunicorn with four threads in one worker, so four sensor
    POSTs can be inside `get_current_game()` at the same time."""

    def test_concurrent_calls_make_one_presence_request(self):
        import threading

        started = threading.Barrier(4)

        def slow_presence():
            time.sleep(0.05)
            return presence(availability='unavailable')

        self.user.get_presence.side_effect = slow_presence
        client = self.make_client(presence_ttl=60)

        def call():
            started.wait()
            client.get_current_game()

        threads = [threading.Thread(target=call) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.user.get_presence.assert_called_once()
