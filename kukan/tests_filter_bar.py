"""Phase 11: the list-page chrome, after the first HTMX version regressed it.

The Vue list page had three things the first server-rendered version lost, all
visible in a screenshot rather than in a test:

* a white background — Bulma 1.x added `prefers-color-scheme: dark`, which
  0.9.4 did not have, so the site went black on any machine set to dark;
* pagination as `1 2 … 310`, not 310 links;
* filters hidden behind an "add filter" dropdown, each an applied-on-demand
  chip, rather than every widget stacked inline above the table and applying
  on every keystroke.

These pin all three. They are deliberately about structure — which elements
exist, what they target, what is in the query string — because that is the
part a future change can break silently. Whether the dropdown *opens* is
Alpine's job and needs a browser.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from kukan.models import Kanji, Kotowaza


class ListPageTestBase(TestCase):
    fixtures = ['baseline', '閲', '覧']
    url_name = 'kukan:kotowaza_list'

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')

    def get(self, **params):
        response = self.client.get(reverse(self.url_name), params)
        self.assertEqual(response.status_code, 200)
        return response


class LightThemeTest(ListPageTestBase):
    def test_the_theme_is_pinned_to_light(self):
        """Bulma 1.x ships `@media (prefers-color-scheme: dark)`; Bulma 0.9.4,
        which this replaced, did not. Without `data-theme` the upgrade turned
        the whole site black for anyone whose OS is set to dark, with no
        stylesheet in this repository having changed."""
        self.assertContains(self.get(), 'data-theme="light"')

    def test_every_page_gets_it_not_just_the_list_pages(self):
        for url in [reverse('login'), reverse('kukan:index'),
                    reverse('kukan:stats'), reverse('tempmon:session_list')]:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'data-theme="light"')


class PaginationTest(ListPageTestBase):
    def setUp(self):
        super().setUp()
        # 15 pages at 20 per page: enough for the window to elide.
        for i in range(300):
            Kotowaza.objects.create(kotowaza=f'諺{i:03}', yomi=f'よみ{i:03}')

    def test_a_long_list_elides_rather_than_linking_every_page(self):
        """kanji_list is 310 pages, and the first version emitted 310 links."""
        response = self.get(page=8)
        self.assertLess(response.content.decode().count('pagination-link'), 12)
        self.assertContains(response, 'pagination-ellipsis')

    def test_the_window_keeps_the_ends_and_the_current_page(self):
        window = self.get(page=8).context['page_window']
        self.assertEqual(window[0], 1)
        self.assertEqual(window[-1], 15)
        self.assertIn(8, window)

    def test_the_first_page_is_always_reachable(self):
        window = self.get(page=15).context['page_window']
        self.assertEqual(window[0], 1)

    def test_a_single_page_has_no_pagination_at_all(self):
        Kotowaza.objects.all().delete()
        Kotowaza.objects.create(kotowaza='犬も歩けば棒に当たる')
        response = self.get()
        self.assertEqual(response.context['page_window'], [])
        self.assertNotContains(response, 'pagination-link')

    def test_previous_is_disabled_on_the_first_page(self):
        response = self.get(page=1)
        self.assertContains(response, 'pagination-previous" disabled')

    def test_next_is_disabled_on_the_last_page(self):
        response = self.get(page=15)
        self.assertContains(response, 'pagination-next" disabled')

    def test_the_window_is_a_list_not_a_generator(self):
        """get_elided_page_range returns a generator. Left as one, the
        template consumes it and anything looking afterwards sees nothing."""
        self.assertIsInstance(self.get(page=8).context['page_window'], list)


class StatsLineTest(ListPageTestBase):
    def test_the_count_and_query_time_are_shown(self):
        Kotowaza.objects.create(kotowaza='犬も歩けば棒に当たる')
        response = self.get()
        self.assertContains(response, '件')
        self.assertContains(response, 'Q:')
        self.assertIsInstance(response.context['query_ms'], int)

    def test_the_client_timings_have_somewhere_to_land(self):
        """S and T are filled in by static/js/stats.js on an htmx swap; the
        server only supplies the slots."""
        response = self.get()
        self.assertContains(response, 'data-stat="server"')
        self.assertContains(response, 'data-stat="total"')
        self.assertContains(response, 'id="results-stats"')


class FilterBarTest(ListPageTestBase):
    url_name = 'kukan:kanji_list'

    def test_no_filter_in_the_url_means_no_chips(self):
        response = self.get()
        self.assertEqual(response.context['active_filter_labels'], [])
        self.assertContains(response, 'ﾌｨﾙﾀｰ追加')

    def test_a_filter_with_a_value_puts_its_chip_up(self):
        response = self.get(**{'漢字': '閲'})
        self.assertEqual(response.context['active_filter_labels'], ['漢字'])

    def test_show_puts_a_chip_up_without_a_value(self):
        """Adding a filter has to survive the round-trip that applies it, or
        the chip you just added disappears as soon as anything is applied."""
        response = self.get(_show='部首')
        self.assertEqual(response.context['active_filter_labels'], ['部首'])

    def test_show_keeps_the_order_the_filters_were_added_in(self):
        """`_show` is written in the order the chips were added, so it is the
        order they come back in -- not the order the view declares them.

        The view lists 漢字 before 部首; asking for them the other way round has
        to survive the round trip, or the bar reshuffles itself on every reload
        and a chip you just added jumps somewhere else.
        """
        response = self.get(**{'_show': '部首,漢字'})
        self.assertEqual(response.context['active_filter_labels'],
                         ['部首', '漢字'])

    def test_a_valued_filter_missing_from_show_is_appended(self):
        """A hand-edited or bookmarked URL can carry a value without naming the
        filter in `_show`. It still gets a chip, after the ones whose position
        is known, since nothing records where the user would have put it.
        """
        response = self.get(**{'漢字': '閲', '_show': '部首'})
        self.assertEqual(response.context['active_filter_labels'],
                         ['部首', '漢字'])

    def test_yomi_chip_shows_the_reading_not_the_encoding(self):
        """A 読み value packs the text with its radio settings. The chip has to
        show the reading and the options that actually narrow the search --
        "せい (始/音)" -- and not the stored "せい_位始_読音_常全", which reads
        as a fragment of the URL rather than as a search.
        """
        response = self.get(**{'読み': 'せい_位始_読音_常全'})
        content = response.content.decode()
        self.assertIn('せい (始/音)', content)
        self.assertNotIn("'せい_位始_読音_常全')", content)

    def test_yomi_chip_omits_the_default_options(self):
        """位致 / 読両 / 常全 are what the filter does anyway, so naming them
        would make every chip longer for nothing.
        """
        response = self.get(**{'読み': 'せい_位致_読両_常全'})
        self.assertIn("'せい'", response.content.decode())

    def test_a_repeated_label_is_not_listed_twice(self):
        response = self.get(**{'漢字': '閲', '_show': '漢字'})
        self.assertEqual(response.context['active_filter_labels'], ['漢字'])

    def test_every_filter_is_rendered_even_when_inactive(self):
        """The chips are server-rendered and shown with x-show, because the
        widgets inside them are Django partials Alpine cannot build."""
        response = self.get()
        for label in response.context['all_filter_labels']:
            with self.subTest(label=label):
                self.assertContains(response, f"filterChip(\'{label}\'")

    def test_an_inactive_filter_is_inside_a_disabled_fieldset(self):
        """Otherwise its hidden input is still submitted, and a filter you
        removed keeps filtering."""
        response = self.get()
        self.assertContains(response, ':disabled="!isActive(name)"')

    def test_the_form_carries_the_sort_so_applying_does_not_drop_it(self):
        response = self.get(sort_by='-strokes')
        self.assertContains(response, 'name="sort_by" value="-strokes"')

    def test_the_form_always_resets_to_page_one(self):
        """Whatever page you were on, applying a filter starts again: the row
        that was on page 12 is not the row that will be there afterwards."""
        self.assertContains(self.get(), 'name="page" value="1"')
        self.assertContains(self.get(page=1), 'name="page" value="1"')

    def test_the_form_targets_the_bar_and_the_table_together(self):
        response = self.get()
        self.assertContains(response, 'hx-target="#filter-results"')

    def test_nothing_applies_on_keystroke(self):
        """The first version had `hx-trigger="input changed delay:400ms"`,
        which re-queried a 6,000-row table on every character typed."""
        content = self.get().content.decode()
        self.assertNotIn('input changed', content)
        self.assertIn('hx-trigger="apply"', content)


class SwapTargetTest(ListPageTestBase):
    url_name = 'kukan:kanji_list'

    def test_a_filter_apply_replaces_the_bar_as_well_as_the_rows(self):
        response = self.client.get(
            reverse(self.url_name),
            HTTP_HX_REQUEST='true', HTTP_HX_TARGET='filter-results')
        self.assertContains(response, 'id="filter-results"')
        self.assertContains(response, 'id="filter-form"')
        self.assertContains(response, 'id="results"')
        self.assertNotContains(response, 'navbar-burger')

    def test_a_sort_or_page_click_replaces_only_the_rows(self):
        """Re-rendering the bar there would close a dropdown the user has
        open, and there is nothing in it that a sort changes."""
        response = self.client.get(
            reverse(self.url_name),
            HTTP_HX_REQUEST='true', HTTP_HX_TARGET='results')
        self.assertContains(response, 'id="results"')
        self.assertNotContains(response, 'id="filter-form"')

    def test_a_normal_request_still_renders_the_whole_page(self):
        response = self.get()
        self.assertContains(response, 'navbar-burger')
        self.assertContains(response, 'id="filter-results"')


class FilteringStillWorksTest(ListPageTestBase):
    """The rewrite is chrome. These are the behaviours underneath it."""

    url_name = 'kukan:kanji_list'

    def test_a_filter_still_narrows_the_result(self):
        response = self.get(**{'漢字': '閲'})
        self.assertEqual([k.pk for k in response.context['object_list']], ['閲'])

    def test_a_filter_survives_a_page_link(self):
        response = self.get(**{'漢字': '閲', 'page': 1})
        self.assertEqual([k.pk for k in response.context['object_list']], ['閲'])

    def test_show_alone_does_not_filter_anything(self):
        """`_show` is display state, not a query. It must never reach
        FFilter.add_to_query."""
        everything = self.get().context['paginator'].count
        self.assertEqual(self.get(_show='漢字').context['paginator'].count,
                         everything)
        self.assertEqual(Kanji.objects.count(), everything)
