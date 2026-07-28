"""Tests for the tempmon views and the PSN wrapper.

`tempmon/views.py` was the least-covered module in the project and carries two
of the modernization's sharper edges:

* **PSNAWP.** Stage 8 moves to 3.0.3, a major bump. `PSN` reaches past the
  library's public API into `psnawp._request_builder` and imports `BASE_PATH`
  and `API_PATH` from `psnawp_api.utils.endpoints`, none of which is covered by
  the library's compatibility promises. The tests below mock at that seam, so
  they describe exactly which private attributes are being relied on — read
  them as the porting checklist for that stage.

* **Pickle.** `PlaySession.data_points` is a pickled dict in a BinaryField,
  holding every reading ever recorded. Stage 5 moves to Python 3.12. A pickle
  round-trip is asserted explicitly here because a failure would not be a
  crash: it would be historical sessions quietly failing to render.

The live-network test for PSN stays in `tests.py`, gated on `psn_token`. These
are the offline counterparts, so the PSN code paths have some cover on a
machine with no credentials.
"""
import datetime as dt
import json
import pickle
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from tempmon.models import DataPoint, GamePerSessionInfo, PlaySession, PsGame
from tempmon.views import (FGenericMinMaxDurationMin, PSN,
                           PlaySessionGraphView, format_duration)

# A session with a known shape: three games, some idle time, 10-second steps.
SESSION_START = 1703643862  # 2023-12-27T11:24:22+09:00


class LoggedInTestCase(TestCase):
    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')


class TestFGenericMinMaxDurationMin(TestCase):
    """Duration filter: the user types minutes, the column stores timedeltas."""

    @classmethod
    def setUpTestData(cls):
        for minutes in [5, 30, 90, 240]:
            start = dt.datetime(2024, 1, 1, 12, 0,
                                tzinfo=dt.timezone(dt.timedelta(hours=9)))
            PlaySession.objects.create(
                start_time=start,
                end_time=start + dt.timedelta(minutes=minutes),
                start_temp=20.0, max_temp=21.0, data_points=b'',
                duration=dt.timedelta(minutes=minutes))

    def setUp(self):
        self.flt = FGenericMinMaxDurationMin('Duration (min)', 'duration')

    def assertMinutes(self, flt_string, expected):
        result = self.flt.add_to_query(flt_string, PlaySession.objects.all())
        self.assertEqual(
            sorted(int(s.duration.total_seconds() / 60) for s in result),
            sorted(expected))

    def test_to_timedelta_converts_minutes(self):
        self.assertEqual(FGenericMinMaxDurationMin.to_timedelta('90'),
                         dt.timedelta(minutes=90))

    def test_closed_range(self):
        self.assertMinutes('30~90', [30, 90])

    def test_open_ended_upper(self):
        self.assertMinutes('90~', [90, 240])

    def test_open_ended_lower(self):
        self.assertMinutes('~30', [5, 30])

    def test_only_range_forms_work_known_defect(self):
        """KNOWN DEFECT, pinned rather than endorsed.

        `add_to_query` here is a copy of `FGenericMinMax.add_to_query` with the
        minutes-to-timedelta conversion bolted on, and the conversion landed in
        the wrong two places:

        * the '≠ ' branch converts before splitting on '~', so it calls
          int() on the whole remainder ('30~90') and raises;
        * the non-range branch passes the raw string to a DurationField
          without converting at all.

        Net effect: of the six input shapes the filter widget can produce, only
        the three plain ranges work. Everything else is a 500 on
        `/tempmon/session_list/` and `/tempmon/game_list/`:

            '30'      -> AttributeError  (str has no attribute 'days')
            '≠ 30'    -> TypeError       ('~' in timedelta)
            '≠ 30~90' -> ValueError      (int('30~90'))

        The fix is to mirror the base class — strip the prefix, split, then
        convert each bound — but that is a behaviour change and belongs in its
        own commit. This test turns red when someone makes it.
        """
        qry = PlaySession.objects.all()
        with self.assertRaises(AttributeError):
            list(self.flt.add_to_query('30', qry))
        with self.assertRaises(TypeError):
            list(self.flt.add_to_query('≠ 30', qry))
        with self.assertRaises(ValueError):
            list(self.flt.add_to_query('≠ 30~90', qry))


class TestFormatDuration(TestCase):
    """Renders the play-time column as H:MM."""

    def test_hours_and_minutes(self):
        self.assertEqual(format_duration(dt.timedelta(hours=2, minutes=5)),
                         '2:05')

    def test_minutes_are_zero_padded(self):
        self.assertEqual(format_duration(dt.timedelta(minutes=7)), '0:07')

    def test_over_twenty_four_hours_does_not_wrap(self):
        """Play time accumulates across sessions, so it exceeds a day."""
        self.assertEqual(format_duration(dt.timedelta(hours=30)), '30:00')

    def test_none_is_zero(self):
        """`play_time` is nullable for a game that was never finished."""
        self.assertEqual(format_duration(None), '0:00')

    def test_seconds_are_truncated_not_rounded(self):
        self.assertEqual(format_duration(dt.timedelta(minutes=1, seconds=59)),
                         '0:01')


class SessionViewTestBase(LoggedInTestCase):
    """Builds one session covering idle time and two different games."""

    def setUp(self):
        super().setUp()
        self.game_a = PsGame.objects.create(title_id='PPSA01', name='Game A')
        self.game_b = PsGame.objects.create(title_id='PPSA02', name='Game B')

        # (offset seconds, temperature, game pk) -- idle, A, A, B, idle
        self.points = [
            (0, 20.0, -1),
            (60, 22.0, self.game_a.pk),
            (120, 25.0, self.game_a.pk),
            (180, 27.0, self.game_b.pk),
            (240, 24.0, -1),
        ]
        for offset, temp, game_pk in self.points:
            self.session = PlaySession.add_point(
                DataPoint(SESSION_START, SESSION_START + offset,
                          temp, 30.0, 1000.0),
                game_pk)


class TestPlaySessionGraphView(SessionViewTestBase):
    """The chart page: series data plus coloured background bands per game."""

    def get_context(self):
        response = self.client.get(
            reverse('session', kwargs={'pk': self.session.pk}))
        self.assertEqual(response.status_code, 200)
        return response.context

    def test_requires_login(self):
        response = Client().get(
            reverse('session', kwargs={'pk': self.session.pk}))
        self.assertEqual(response.status_code, 302)

    def test_duration_is_end_minus_start(self):
        self.assertEqual(self.get_context()['duration'],
                         dt.timedelta(seconds=240))

    def test_temp_data_x_is_minutes_from_session_start(self):
        temp_data = self.get_context()['temp_data']
        self.assertEqual([p['x'] for p in temp_data], [0, 1, 2, 3, 4])
        self.assertEqual([p['y'] for p in temp_data],
                         [20.0, 22.0, 25.0, 27.0, 24.0])

    def test_temp_delta_is_the_difference_between_consecutive_points(self):
        """One shorter than temp_data; y is the change, not the value."""
        delta = self.get_context()['temp_delta']
        self.assertEqual(len(delta), len(self.points) - 1)
        self.assertEqual([p['y'] for p in delta], [2.0, 3.0, 2.0, -3.0])
        self.assertEqual([p['x'] for p in delta], [1, 2, 3, 4])

    def test_games_legend_excludes_idle_time(self):
        """-1 is the 'not playing' sentinel and gets no legend entry."""
        legend = self.get_context()['games_legend']
        self.assertEqual(set(legend), {self.game_a.pk, self.game_b.pk})

    def test_games_legend_holds_name_colour_and_duration(self):
        legend = self.get_context()['games_legend']
        name, colour, duration = legend[self.game_a.pk]
        self.assertEqual(name, 'Game A')
        self.assertIn(colour, PlaySessionGraphView.bg_colors)
        self.assertEqual(duration, dt.timedelta(seconds=120))

    def test_games_get_distinct_colours(self):
        legend = self.get_context()['games_legend']
        colours = [entry[1] for entry in legend.values()]
        self.assertEqual(len(colours), len(set(colours)))

    def test_graph_background_covers_only_played_spans(self):
        background = self.get_context()['graph_background']
        # Idle spans are dropped, so only the two game bands remain.
        self.assertEqual(len(background), 2)
        for start, end, colour in background:
            self.assertLess(start, end)
            self.assertIn(colour, PlaySessionGraphView.bg_colors)

    def test_switch_link_points_at_the_details_page(self):
        self.assertEqual(self.get_context()['switch_link'],
                         {'path_name': 'session_details', 'label': 'Details'})

    def test_psn_ok_reflects_the_global(self):
        """TempMonViewMixin drives a red header when PSN login failed."""
        with patch('tempmon.views.psn', None):
            self.assertIs(self.get_context()['psn_ok'], False)
        with patch('tempmon.views.psn', MagicMock()):
            self.assertIs(self.get_context()['psn_ok'], True)


class TestGetBackgroundMatrix(TestCase):
    """The span generator, driven directly for the edge cases."""

    def run_matrix(self, game_ids):
        data = {i: (10.0, 1.0, 1.0, g) for i, g in enumerate(game_ids, start=1)}
        return list(PlaySessionGraphView.get_background_matrix(
            data, sorted(data.keys())))

    def test_single_point_yields_a_zero_length_span(self):
        self.assertEqual(self.run_matrix([-1]), [(1, 1, -1)])

    def test_uninterrupted_game_is_one_span(self):
        self.assertEqual(self.run_matrix([5, 5, 5]), [(1, 3, 5)])

    def test_alternating_games_split_into_spans(self):
        """Note the first span is zero-width: a switch yields the span ending
        at the *previous* point, so the opening band has no extent until at
        least two consecutive readings share a game."""
        self.assertEqual(self.run_matrix([1, 2, 1]),
                         [(1, 1, 1), (1, 2, 2), (2, 3, 1)])

    def test_returning_to_a_game_creates_a_second_span(self):
        """Spans are contiguous runs, not per-game totals."""
        spans = self.run_matrix([1, 1, 2, 1, 1])
        self.assertEqual([game for _, _, game in spans], [1, 2, 1])


class TestPlaySessionDetailsView(SessionViewTestBase):
    """The tabular view of one session."""

    def get_context(self):
        response = self.client.get(
            reverse('session_details', kwargs={'pk': self.session.pk}))
        self.assertEqual(response.status_code, 200)
        return response.context

    def test_requires_login(self):
        response = Client().get(
            reverse('session_details', kwargs={'pk': self.session.pk}))
        self.assertEqual(response.status_code, 302)

    def test_headers(self):
        self.assertEqual(
            self.get_context()['data']['headers'],
            ['Time', 'Duration', 'Game', 'Temperature', 'Humidity',
             'Pressure'])

    def test_one_row_per_reading(self):
        self.assertEqual(len(self.get_context()['data']['rows']),
                         len(self.points))

    def test_time_is_rendered_in_jst(self):
        """`datetime.fromtimestamp(...).astimezone(ZoneInfo('Asia/Tokyo'))` —
        the session starts at 11:24:22 JST."""
        self.assertEqual(self.get_context()['data']['rows'][0][0], '11:24:22')

    def test_duration_column_counts_from_session_start(self):
        rows = self.get_context()['data']['rows']
        self.assertEqual(rows[0][1], dt.timedelta(0))
        self.assertEqual(rows[-1][1], dt.timedelta(seconds=240))

    def test_idle_rows_show_na(self):
        rows = self.get_context()['data']['rows']
        self.assertEqual(rows[0][2], 'N/A')

    def test_game_rows_show_the_game(self):
        rows = self.get_context()['data']['rows']
        self.assertEqual(str(rows[1][2]), 'Game A')

    def test_deleted_game_falls_back_to_na(self):
        """A pk in the pickle with no matching row must not 500 the page."""
        GamePerSessionInfo.objects.all().delete()
        self.game_a.delete()
        rows = self.get_context()['data']['rows']
        self.assertEqual(rows[1][2], 'N/A')

    def test_measurements_are_formatted_to_fixed_precision(self):
        row = self.get_context()['data']['rows'][0]
        self.assertEqual(row[3], '20.00')   # temperature, 2dp
        self.assertEqual(row[4], '30.00')   # humidity, 2dp
        self.assertEqual(row[5], '1000.0')  # pressure, 1dp

    def test_switch_link_points_back_at_the_graph(self):
        self.assertEqual(self.get_context()['switch_link'],
                         {'path_name': 'session', 'label': 'Graph'})


class TestDataPointsPickle(TestCase):
    """`PlaySession.data_points` is a pickled dict — the format of record.

    Stage 5 moves to Python 3.12. These assertions describe what is in the
    column so that a change in pickling shows up here rather than as a session
    page that fails to render years of history.
    """

    def test_round_trip_preserves_the_dict(self):
        session = PlaySession.add_point(
            DataPoint(SESSION_START, SESSION_START, 21.9, 30.1, 10000.3))
        session.refresh_from_db()
        self.assertEqual(session.data_dict,
                         {SESSION_START: (21.9, 30.1, 10000.3, -1)})

    def test_keys_are_integer_timestamps_and_values_are_four_tuples(self):
        session = PlaySession.add_point(
            DataPoint(SESSION_START, SESSION_START, 21.9, 30.1, 10000.3))
        (key, value), = session.data_dict.items()
        self.assertIsInstance(key, int)
        self.assertIsInstance(value, tuple)
        self.assertEqual(len(value), 4)

    def test_stored_bytes_are_a_plain_pickled_dict(self):
        """No custom classes in the payload: a dict of int -> tuple of floats.
        That is what makes it portable across interpreter versions."""
        session = PlaySession.add_point(
            DataPoint(SESSION_START, SESSION_START, 21.9, 30.1, 10000.3))
        session.refresh_from_db()
        loaded = pickle.loads(session.data_points)
        self.assertIs(type(loaded), dict)

    def test_current_temp_reads_the_latest_point(self):
        for offset, temp in [(0, 20.0), (60, 25.0), (30, 22.0)]:
            session = PlaySession.add_point(
                DataPoint(SESSION_START, SESSION_START + offset,
                          temp, 30.0, 1000.0))
        # Latest by timestamp, not by insertion order.
        self.assertEqual(session.current_temp, 25.0)


class PlaytimeViewTestBase(LoggedInTestCase):
    """Two games played across three months spanning a year boundary."""

    def setUp(self):
        super().setUp()
        self.game_a = PsGame.objects.create(title_id='PPSA01', name='Game A')
        self.game_b = PsGame.objects.create(title_id='PPSA02', name='Game B')
        jst = dt.timezone(dt.timedelta(hours=9))

        # (start, game, minutes)
        self.plays = [
            (dt.datetime(2025, 11, 10, 20, 0, tzinfo=jst), self.game_a, 60),
            (dt.datetime(2025, 12, 5, 20, 0, tzinfo=jst), self.game_a, 30),
            (dt.datetime(2025, 12, 6, 20, 0, tzinfo=jst), self.game_b, 120),
            (dt.datetime(2026, 1, 8, 20, 0, tzinfo=jst), self.game_b, 90),
        ]
        for start, game, minutes in self.plays:
            session = PlaySession.objects.create(
                start_time=start,
                end_time=start + dt.timedelta(minutes=minutes),
                start_temp=20.0, max_temp=25.0,
                data_points=pickle.dumps({}),
                duration=dt.timedelta(minutes=minutes))
            GamePerSessionInfo.objects.create(
                session=session, game=game,
                duration=dt.timedelta(minutes=minutes))


class TestPlaytimeMonthlyView(PlaytimeViewTestBase):
    def get_chart(self, frozen='2026-01-20 12:00:00'):
        from freezegun import freeze_time
        with freeze_time(frozen):
            response = self.client.get(reverse('playtime_monthly'))
        self.assertEqual(response.status_code, 200)
        return json.loads(response.context['chart_data'])

    def test_requires_login(self):
        self.assertEqual(
            Client().get(reverse('playtime_monthly')).status_code, 302)

    def test_chart_shape(self):
        chart = self.get_chart()
        self.assertEqual(set(chart), {'months', 'games', 'series'})

    def test_months_are_year_month_strings_in_order(self):
        self.assertEqual(self.get_chart()['months'],
                         ['2025-11', '2025-12', '2026-01'])

    def test_games_are_sorted_by_name(self):
        self.assertEqual(self.get_chart()['games'], ['Game A', 'Game B'])

    def test_series_are_hours_per_month_per_game(self):
        series = {s['name']: s['data'] for s in self.get_chart()['series']}
        self.assertEqual(series['Game A'], [1.0, 0.5, 0])
        self.assertEqual(series['Game B'], [0, 2.0, 1.5])

    def test_every_series_covers_every_month(self):
        chart = self.get_chart()
        for s in chart['series']:
            self.assertEqual(len(s['data']), len(chart['months']))

    def test_list_title(self):
        response = self.client.get(reverse('playtime_monthly'))
        self.assertEqual(response.context['list_title'], 'Playtime per Month')

    def test_games_without_play_time_are_ignored(self):
        """The queryset filters on play_time__isnull=False."""
        PsGame.objects.create(title_id='PPSA99', name='Never Played')
        self.assertNotIn('Never Played', self.get_chart()['games'])


class TestPlaytimeYearlyView(PlaytimeViewTestBase):
    def get_chart(self):
        response = self.client.get(reverse('playtime_yearly'))
        self.assertEqual(response.status_code, 200)
        return json.loads(response.context['chart_data'])

    def test_requires_login(self):
        self.assertEqual(
            Client().get(reverse('playtime_yearly')).status_code, 302)

    def test_chart_shape_uses_years_not_months(self):
        chart = self.get_chart()
        self.assertEqual(set(chart), {'years', 'games', 'series'})

    def test_years_are_in_order(self):
        self.assertEqual(self.get_chart()['years'], ['2025', '2026'])

    def test_series_aggregate_the_whole_year(self):
        series = {s['name']: s['data'] for s in self.get_chart()['series']}
        self.assertEqual(series['Game A'], [1.5, 0])
        self.assertEqual(series['Game B'], [2.0, 1.5])

    def test_list_title(self):
        response = self.client.get(reverse('playtime_yearly'))
        self.assertEqual(response.context['list_title'], 'Playtime per Year')


class TestPsnWrapper(TestCase):
    """`PSN` offline, against a mocked psnawp.

    Each mock here marks a place where the code depends on PSNAWP internals.
    When Stage 8 bumps to 3.0.3, these are the attributes to re-check first.
    """

    def make_psn(self, psnawp_cls):
        instance = psnawp_cls.return_value
        instance.me.return_value.account_id = 'acct-1'
        return PSN('token'), instance

    @patch('tempmon.views.PSNAWP')
    def test_constructor_requests_japanese_locale(self, psnawp_cls):
        self.make_psn(psnawp_cls)
        psnawp_cls.assert_called_once_with(
            'token', accept_language='ja', country='JP')

    @patch('tempmon.views.PSNAWP')
    def test_get_current_game_returns_minus_one_when_offline(self, psnawp_cls):
        psn, instance = self.make_psn(psnawp_cls)
        instance.user.return_value.get_presence.return_value = {
            'basicPresence': {'availability': 'unavailable'}}
        self.assertEqual(psn.get_current_game(), -1)

    @patch('tempmon.views.PSNAWP')
    def test_get_current_game_returns_minus_one_when_not_playing(
            self, psnawp_cls):
        psn, instance = self.make_psn(psnawp_cls)
        instance.user.return_value.get_presence.return_value = {
            'basicPresence': {
                'availability': 'availableToPlay',
                'primaryPlatformInfo': {'onlineStatus': 'offline'}}}
        self.assertEqual(psn.get_current_game(), -1)

    @patch('tempmon.views.PSNAWP')
    def test_get_current_game_without_a_title_returns_minus_one(
            self, psnawp_cls):
        """Online but on the dashboard: no gameTitleInfoList key."""
        psn, instance = self.make_psn(psnawp_cls)
        instance.user.return_value.get_presence.return_value = {
            'basicPresence': {
                'availability': 'availableToPlay',
                'primaryPlatformInfo': {'onlineStatus': 'online'}}}
        self.assertEqual(psn.get_current_game(), -1)

    @patch('tempmon.views.PSNAWP')
    def test_get_current_game_returns_the_game_pk(self, psnawp_cls):
        psn, instance = self.make_psn(psnawp_cls)
        game = PsGame.objects.create(title_id='PPSA01', name='Known Game')
        instance.user.return_value.get_presence.return_value = {
            'basicPresence': {
                'availability': 'availableToPlay',
                'primaryPlatformInfo': {'onlineStatus': 'online'},
                'gameTitleInfoList': [{'npTitleId': 'PPSA01'}]}}
        self.assertEqual(psn.get_current_game(), game.pk)

    @patch('tempmon.views.PSNAWP')
    def test_get_game_pk_reuses_an_existing_row(self, psnawp_cls):
        psn, _ = self.make_psn(psnawp_cls)
        game = PsGame.objects.create(title_id='PPSA01', name='Known Game')
        self.assertEqual(psn.get_game_pk('PPSA01'), game.pk)
        self.assertEqual(PsGame.objects.count(), 1)

    @patch('tempmon.views.PSNAWP')
    def test_get_game_pk_creates_a_row_with_the_japanese_name(self,
                                                              psnawp_cls):
        psn, instance = self.make_psn(psnawp_cls)
        # The private request builder the JP-name lookup goes through.
        instance._request_builder.get.return_value.json.return_value = [
            {'name': 'ゲーム名'}]
        pk = psn.get_game_pk('PPSA01')
        self.assertEqual(PsGame.objects.get(pk=pk).name, 'ゲーム名')

    @patch('tempmon.views.PSNAWP')
    def test_unknown_title_is_recorded_as_a_placeholder(self, psnawp_cls):
        """PSNAWPNotFound must not lose the reading; the row is created with a
        sentinel name so the session still attributes its time."""
        from psnawp_api.core.psnawp_exceptions import PSNAWPNotFound

        psn, instance = self.make_psn(psnawp_cls)
        instance.game_title.side_effect = PSNAWPNotFound('nope')
        pk = psn.get_game_pk('PPSA-UNKNOWN')
        self.assertEqual(PsGame.objects.get(pk=pk).name, '__UNKNOWN__')
