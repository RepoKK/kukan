"""Tests for the bustime scraper.

`bustime/views.py` is the most dependency-exposed module in the project: it
leans on pandas' `read_html`, numpy's NaN handling and pytz's `localize`, all
against markup nobody here controls. Every one of those is due to move during
the modernization:

* pandas 3 changes `read_html` and removes positional `Series[0]` indexing,
  which `get_time_to_next_hana` uses.
* pytz is superseded by `zoneinfo`, and `localize()` has no zoneinfo
  equivalent — that call has to be rewritten, not just re-imported.
* numpy 2 tightened scalar conversion, which `np.isnan` and `int(minute)` feed.

The pages are recorded under `fixtures/Web/` as raw HTML rather than as pickled
`requests.Response` objects (the older `FixWebKukan` style). A pickle carries
the library's own class layout, so it stops loading the moment `requests` is
upgraded — precisely when these tests need to run. Raw HTML has no such
coupling.

Times are frozen because the module compares against `datetime.now()`; without
that these tests would pass or fail depending on the hour they ran.
"""
import datetime as dt
import json
import os
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from freezegun import freeze_time

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'Web')

# The stop/line/direction the site actually asks for, from BusTimeMain.
SHINJUKU = ('新宿駅西口', '白６１', '練馬駅・練馬車庫前')


def load_page(name):
    with open(os.path.join(FIXTURE_DIR, name), 'rb') as f:
        return f.read()


class GetBusTimeTest(TestCase):
    """`get_bus_time` parses a timetable page into future departures.

    The recorded page is a 平日 (weekday) timetable and contains all three
    diagrams — 平日, 土曜, 休日 — as separate tables. The function picks one by
    reading which diagram is in service from the page text, so these tests
    exercise the selection as well as the parsing.
    """

    def setUp(self):
        self.page = load_page('timetable_shinjuku.html')

    def get_times(self, jst_wall_clock, station_args=SHINJUKU):
        """Freeze at the given *Tokyo* wall-clock time.

        The argument is a JST wall clock because that is what the timetable is
        published in and what these assertions reason about. It is converted to
        a real instant before freezing, so the test does not depend on the
        host's timezone — this suite runs on a UTC-clocked container and the
        production box is on JST.
        """
        frozen = dt.datetime.fromisoformat(f'{jst_wall_clock}+09:00')
        from bustime.views import get_bus_time
        with freeze_time(frozen), \
                patch('bustime.views.urllib.request.urlopen') as urlopen:
            urlopen.return_value.read.return_value = self.page
            return get_bus_time('http://example.invalid/', *station_args)

    def test_returns_departures_after_now(self):
        times = self.get_times('2026-07-28 10:00:00')
        self.assertTrue(times, 'no departures parsed from the timetable')
        self.assertTrue(all(t > dt.datetime(2026, 7, 28, 10, 0,
                                            tzinfo=t.tzinfo)
                            for t in times))

    def test_first_departure_is_the_next_one(self):
        times = self.get_times('2026-07-28 10:00:00')
        self.assertEqual(times[0].strftime('%H:%M'), '10:08')

    def test_departures_are_timezone_aware_jst(self):
        """The values go to the template as epoch seconds; a naive datetime
        would be interpreted as UTC and shift every time by nine hours."""
        times = self.get_times('2026-07-28 10:00:00')
        self.assertIsNotNone(times[0].tzinfo)
        self.assertEqual(times[0].utcoffset(), dt.timedelta(hours=9))

    def test_earlier_in_the_day_returns_more_departures(self):
        early = self.get_times('2026-07-28 05:00:00')
        late = self.get_times('2026-07-28 20:00:00')
        self.assertGreater(len(early), len(late))

    def test_after_last_bus_returns_empty(self):
        self.assertEqual(self.get_times('2026-07-28 23:59:00'), [])

    def test_all_departures_are_today(self):
        """`dt.date.today()` is combined with the timetable's hour and minute,
        so a timetable row past midnight would land on the wrong day. Recorded
        page has no such row; this pins that assumption."""
        times = self.get_times('2026-07-28 05:00:00')
        self.assertTrue(all(t.date() == dt.date(2026, 7, 28) for t in times))

    def test_result_depends_on_the_instant_not_the_host_clock(self):
        """The same moment, written in two timezones, must give one answer.

        `get_bus_time` used to do `datetime.now().replace(tzinfo=JST)`, which
        takes the host's wall clock and merely relabels it. That is correct
        only when the host is already on JST — production is, this container
        and CI are not, so the page listed buses that had already departed.

        Freezing the same instant as 10:00+09:00 and as 01:00Z is the cheapest
        way to state that the host's zone must not matter.
        """
        from bustime.views import get_bus_time

        def times_at(frozen):
            with freeze_time(frozen), \
                    patch('bustime.views.urllib.request.urlopen') as urlopen:
                urlopen.return_value.read.return_value = self.page
                return get_bus_time('http://example.invalid/', *SHINJUKU)

        as_jst = times_at(dt.datetime.fromisoformat('2026-07-28 10:00:00+09:00'))
        as_utc = times_at(dt.datetime.fromisoformat('2026-07-28 01:00:00+00:00'))
        self.assertEqual(as_jst, as_utc)
        self.assertTrue(as_jst)

    def test_unknown_station_returns_empty(self):
        """No header matches, so nothing is collected — quietly."""
        times = self.get_times('2026-07-28 10:00:00',
                               ('存在しない停留所', '白６１', '練馬駅・練馬車庫前'))
        self.assertEqual(times, [])

    def test_header_match_depends_on_a_non_breaking_space(self):
        """GUARD, not a behaviour test.

        `get_bus_time` compares the table header against an f-string that
        contains a literal U+00A0 between '】' and the line name, because that
        is what tobus.jp emits (`&nbsp;`) and what pandas hands back.

        The character is invisible in an editor. Reformatting that line,
        running a whitespace-normalising linter over it, or retyping it would
        replace it with U+0020, the header would stop matching, and the page
        would render an empty timetable with no error anywhere. Stage 3 adds
        ruff, which makes that a live risk.

        If this fails, restore the U+00A0 rather than changing the assertion.
        """
        import inspect

        from bustime import views
        source = inspect.getsource(views.get_bus_time)
        self.assertIn('】\xa0{line}', source,
                      'the U+00A0 in the header comparison has been replaced; '
                      'the timetable will silently come back empty')


class GetTimeToNextHanaTest(TestCase):
    """The realtime arrival endpoint, which returns JSON to the Vue page."""

    def call_view(self, page):
        from bustime.views import get_time_to_next_hana
        with patch('bustime.views.requests.get') as requests_get:
            requests_get.return_value.content = page
            response = get_time_to_next_hana(None)
        return json.loads(response.content)

    def test_recorded_page_yields_a_stop_and_a_wait(self):
        data = self.call_view(load_page('realtime_hanazono.html'))
        self.assertEqual(set(data),
                         {'real_next_bus_stop', 'real_next_bus_wait'})
        self.assertEqual(data['real_next_bus_stop'], 2)
        self.assertEqual(data['real_next_bus_wait'], '6')

    def test_wait_is_a_string_and_stop_is_an_int(self):
        """The Vue side renders the wait directly and compares the stop
        numerically, so the types are part of the contract."""
        data = self.call_view(load_page('realtime_hanazono.html'))
        self.assertIsInstance(data['real_next_bus_stop'], int)
        self.assertIsInstance(data['real_next_bus_wait'], str)

    def test_leading_zero_is_stripped_from_the_wait(self):
        """The page says '06分待'; the UI shows '6'."""
        data = self.call_view(load_page('realtime_hanazono.html'))
        self.assertEqual(data['real_next_bus_wait'], '6')

    def test_no_bus_found_returns_the_sentinel_values(self):
        """The IndexError branch: -1 and '-' mean 'nothing approaching'."""
        data = self.call_view(self.build_status_page(''))
        self.assertEqual(data['real_next_bus_stop'], -1)
        self.assertEqual(data['real_next_bus_wait'], '-')

    def test_bus_arriving_imminently_returns_zero(self):
        """'まもなく' has no minute count, so both values collapse to 0."""
        data = self.call_view(
            self.build_status_page('新宿駅西口行まもなく', in_first_column=True))
        self.assertEqual(data['real_next_bus_stop'], 0)
        self.assertEqual(data['real_next_bus_wait'], 0)

    @staticmethod
    def build_status_page(cell_text, in_first_column=False):
        """Minimal stand-in for the realtime page.

        The view reads `pd.read_html(page)[2]`, so the document needs two
        tables before the one that matters. Only used for the states the
        recorded page cannot show (no bus, bus imminent).
        """
        position = 1 if in_first_column else 5
        # Column 0 always carries a stop name so the table is never wholly
        # empty: pandas drops empty tables, which would shift the [2] index.
        cells = ''.join(
            f'<td>{"花園町" if i == 0 else (cell_text if i == position else "")}'
            f'</td>' for i in range(15))
        blank_row = ''.join(
            f'<td>{"停留所" if i == 0 else ""}</td>' for i in range(15))
        filler = '<table><tr><td>x</td></tr></table>'
        return (f'<html><body>{filler}{filler}'
                f'<table><tr>{cells}</tr>'
                f'<tr>{blank_row}</tr>'
                f'<tr>{blank_row}</tr></table>'
                f'</body></html>').encode()


class BusTimeMainViewTest(TestCase):
    """The page itself. Public — no login — which is asserted in
    kukan.tests_access_control."""

    def setUp(self):
        self.client = Client()
        self.page = load_page('timetable_shinjuku.html')

    def get_page(self, jst_wall_clock='2026-07-28 10:00:00', **params):
        """As GetBusTimeTest.get_times: the time is a Tokyo wall clock."""
        frozen = dt.datetime.fromisoformat(f'{jst_wall_clock}+09:00')
        with freeze_time(frozen), \
                patch('bustime.views.urllib.request.urlopen') as urlopen:
            urlopen.return_value.read.return_value = self.page
            return self.client.get(reverse('bustime:bustime_main'), params)

    def test_renders_without_login(self):
        response = self.get_page()
        self.assertEqual(response.status_code, 200)

    def test_defaults_to_shinjuku(self):
        context = self.get_page().context
        self.assertEqual(context['busStopMain']['name'], '新宿駅西口')
        self.assertEqual(context['busStopOther']['name'], '花園町')

    def test_station_parameter_swaps_the_two_stops(self):
        context = self.get_page(station='花園町').context
        self.assertEqual(context['busStopMain']['name'], '花園町')
        self.assertEqual(context['busStopOther']['name'], '新宿駅西口')

    def test_colour_classes_follow_the_selected_stop(self):
        """Shinjuku is info/success; the reverse direction swaps them."""
        context = self.get_page().context
        self.assertEqual(context['busStopMain']['class'], 'is-info')
        self.assertEqual(context['busStopOther']['class'], 'is-success')

        context = self.get_page(station='花園町').context
        self.assertEqual(context['busStopMain']['class'], 'is-success')
        self.assertEqual(context['busStopOther']['class'], 'is-info')

    def test_each_direction_requests_its_own_timetable_url(self):
        for station, expected in [('新宿駅西口', 'slst=702'),
                                  ('花園町', 'slst=1235')]:
            frozen = dt.datetime.fromisoformat('2026-07-28 10:00:00+09:00')
            with self.subTest(station=station), freeze_time(frozen), \
                        patch('bustime.views.urllib.request.urlopen') as m:
                m.return_value.read.return_value = self.page
                self.client.get(reverse('bustime:bustime_main'),
                                {'station': station})
                self.assertIn(expected, m.call_args[0][0])

    def test_hot_day_is_true_in_summer(self):
        """Drives a hot-weather warning; the window is July to September."""
        self.assertIs(self.get_page('2026-07-28 10:00:00').context['hot_day'],
                      True)

    def test_hot_day_is_false_in_winter(self):
        self.assertIs(self.get_page('2026-01-15 10:00:00').context['hot_day'],
                      False)

    def test_hot_day_boundaries(self):
        """`6 < month < 10`: June is out, July in, September in, October out."""
        for date, expected in [('2026-06-30', False), ('2026-07-01', True),
                               ('2026-09-30', True), ('2026-10-01', False)]:
            with self.subTest(date=date):
                context = self.get_page(f'{date} 10:00:00').context
                self.assertIs(context['hot_day'], expected)

    def test_departures_reach_the_template(self):
        response = self.get_page()
        self.assertTrue(response.context['list_times'])
        # The template emits epoch seconds followed by a literal '000'.
        self.assertContains(response, 'jstimes')
