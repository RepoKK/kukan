"""Contract tests for tempmon's two `FilteredListView` pages.

The kukan pages are covered by `kukan.tests_listview`; these exist because
tempmon reaches the same view class through a different shell
(`tempmon/base_tabs.html`, with the PSN status hero and the tab bar) and
because two of its filters are tempmon's own: `FGenericMinMaxDurationMin`
encodes minutes and re-reads them as timedeltas, and the sessions page is the
only user of `FGenericDateRange` on a real, writable datetime column.
"""
import datetime as dt
import pickle

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from tempmon.models import PlaySession, PsGame


class TempmonListTestBase(TestCase):
    fixtures = ['baseline']

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')

        now = timezone.now()
        self.alpha = PsGame.objects.create(
            title_id='CUSA00001', name='Alpha Quest',
            play_time=dt.timedelta(minutes=30),
            last_played=now - dt.timedelta(days=1))
        self.beta = PsGame.objects.create(
            title_id='CUSA00002', name='Beta Racer',
            play_time=dt.timedelta(minutes=90),
            last_played=now - dt.timedelta(days=2))

        self.short = self._session(now - dt.timedelta(days=3), 20, 21.0)
        self.long = self._session(now - dt.timedelta(days=5), 100, 26.0)

    def _session(self, start, minutes, start_temp):
        """Deliberately not attached to a `PsGame`.

        `GamePerSessionInfo.save()` recomputes the game's `play_time` and
        `last_played` from its sessions, so linking these would silently
        rewrite the two values the games-list tests below assert on.
        """
        return PlaySession.objects.create(
            start_time=start, end_time=start + dt.timedelta(minutes=minutes),
            start_temp=start_temp, max_temp=start_temp + 5,
            data_points=pickle.dumps({}),
            duration=dt.timedelta(minutes=minutes))

    def pks(self, url_name, **params):
        response = self.client.get(reverse(url_name), params)
        self.assertEqual(response.status_code, 200)
        return [obj.pk for obj in response.context['object_list']]


class GamesListContractTest(TempmonListTestBase):
    def test_requires_login(self):
        response = Client().get(reverse('tempmon:game_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_a_normal_request_renders_the_full_page(self):
        response = self.client.get(reverse('tempmon:game_list'))
        self.assertContains(response, 'tabs is-centered')
        self.assertContains(response, '<table')

    def test_an_htmx_request_renders_only_the_table_partial(self):
        response = self.client.get(
            reverse('tempmon:game_list'), HTTP_HX_REQUEST='true')
        self.assertNotContains(response, 'tabs is-centered')
        self.assertContains(response, 'id="results"')

    def test_no_vue_or_buefy_remains(self):
        content = self.client.get(reverse('tempmon:game_list')).content.decode()
        self.assertNotIn('vue_app', content)
        self.assertNotIn('v-filter', content)
        self.assertNotIn('node_modules', content)
        self.assertNotIn('buefy', content.lower())

    def test_default_sort_is_most_recently_played_first(self):
        self.assertEqual(self.pks('tempmon:game_list'),
                         [self.alpha.pk, self.beta.pk])

    def test_string_filter_narrows_by_pk(self):
        self.assertEqual(self.pks('tempmon:game_list', **{'Title': 'Beta'}),
                         [self.beta.pk])

    def test_duration_filter_reads_the_value_as_minutes(self):
        """`FGenericMinMaxDurationMin` is tempmon's own: the widget writes a
        plain number and the filter turns it into a timedelta. Alpha is 30
        minutes, Beta 90, so a `~60` upper bound keeps only Alpha."""
        self.assertEqual(
            self.pks('tempmon:game_list', **{'Duration (min)': '~60'}),
            [self.alpha.pk])

    def test_duration_filter_lower_bound(self):
        self.assertEqual(
            self.pks('tempmon:game_list', **{'Duration (min)': '60~'}),
            [self.beta.pk])

    def test_list_title(self):
        response = self.client.get(reverse('tempmon:game_list'))
        self.assertEqual(response.context['list_title'], 'Game play time')

    def test_play_time_renders_through_the_format_duration_callable(self):
        """Not the raw `0:30:00` a timedelta stringifies to."""
        response = self.client.get(reverse('tempmon:game_list'))
        self.assertContains(response, '0:30')
        self.assertNotContains(response, '0:30:00')


class PlaySessionListContractTest(TempmonListTestBase):
    def test_requires_login(self):
        response = Client().get(reverse('tempmon:session_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_default_sort_is_most_recent_session_first(self):
        self.assertEqual(self.pks('tempmon:session_list'),
                         [self.short.pk, self.long.pk])

    def test_start_time_column_links_to_the_session_graph(self):
        response = self.client.get(reverse('tempmon:session_list'))
        self.assertContains(response,
                            f'href="/tempmon/session/{self.short.pk}/"')

    def test_daterange_filter_narrows_by_pk(self):
        cutoff = (timezone.localtime(self.long.start_time)
                  + dt.timedelta(days=1)).strftime('%Y-%m-%d')
        self.assertEqual(
            self.pks('tempmon:session_list', **{'Start time': f'{cutoff}~'}),
            [self.short.pk])

    def test_duration_filter_narrows_by_pk(self):
        self.assertEqual(
            self.pks('tempmon:session_list', **{'Duration (min)': '~60'}),
            [self.short.pk])

    def test_min_max_filter_on_start_temperature_narrows_by_pk(self):
        self.assertEqual(
            self.pks('tempmon:session_list',
                     **{'Start temperature': '25~'}),
            [self.long.pk])

    def test_every_configured_filter_reaches_the_template(self):
        response = self.client.get(reverse('tempmon:session_list'))
        for label in ['Start time', 'End time', 'Duration (min)',
                      'Start temperature']:
            self.assertContains(response, f'name="{label}"')

    def test_list_title(self):
        response = self.client.get(reverse('tempmon:session_list'))
        self.assertEqual(response.context['list_title'], 'Play sessions')
