"""Contract tests for `AjaxList` and `TableData`.

All five kukan list pages have moved to `FilteredListView` (see
`kukan.tests_listview`); `tempmon:game_list` is now the sole remaining view
still on `AjaxList` and is what this file exercises `AjaxList` itself
through. tempmon's two list views (`game_list`, `session_list`) and their
shared shell are deferred: every other tempmon page still needs Vue/Buefy
(the chart pages are their own later stage; `psnapikey_form.html`'s form
renders through a Buefy widget override that is separate cleanup), so
converting the shared shell now would break them, and there is limited
value in a partial per-page conversion that leaves `AjaxList`/`v-filter/`
in place for its one remaining caller anyway.

The browser loads an HTML shell, then the Vue table re-requests the same URL
with `?ajax=1` and renders whatever JSON comes back. That JSON is an
undeclared API: no serializer, no schema, just whatever `get_list` happens to
assemble.

Two reasons to pin it:

* Whatever eventually replaces this page's frontend, this describes what the
  Vue frontend was given, so the replacement can be checked against the real
  shape instead of against somebody's memory of it.
* `TableData.FieldProps` reads `verbose_name`, `choices` and
  `get_internal_type()` off the model meta API. Those are exactly the surfaces
  Django 6.0 moves, and a change there degrades column labels and types
  silently — the page still renders, it is just wrong. Most of that is now
  pinned directly against `TableData` (`TestTableDataUnit`), independent of
  any view, since `TableData` itself is not going away — `FilteredListView`
  reuses it unchanged.

The HTML-shell path and the ajax path are tested separately because they build
their context by different routes and only the ajax one touches the database.
"""
import datetime as dt
import json
import re

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from kukan.models import Kanji, Kotowaza
from kukan.views import TableData
from tempmon.models import PsGame


def cell_text(value):
    """Strip the anchor that link columns wrap around their value."""
    return re.sub(r'<[^>]+>', '', value)


class AjaxListTestBase(TestCase):
    fixtures = ['baseline', '閲']

    def setUp(self):
        now = timezone.now()
        PsGame.objects.create(
            title_id='CUSA00001', name='Alpha Quest',
            play_time=dt.timedelta(minutes=30),
            last_played=now - dt.timedelta(days=1))
        PsGame.objects.create(
            title_id='CUSA00002', name='Beta Racer',
            play_time=dt.timedelta(minutes=90),
            last_played=now - dt.timedelta(days=2))
        PsGame.objects.create(
            title_id='CUSA00003', name='Alpha Quest 2',
            play_time=dt.timedelta(minutes=45),
            last_played=now - dt.timedelta(days=3))
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def get_ajax(self, url_name, **params):
        params['ajax'] = '1'
        response = self.client.get(reverse(url_name), params)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)


class TestAjaxEnvelope(AjaxListTestBase):
    """The top-level shape of the ajax response, for the one remaining view."""

    def test_envelope_keys(self):
        data = self.get_ajax('tempmon:game_list')
        self.assertEqual(set(data), {'total_results', 'table_data', 'stats'})
        self.assertEqual(set(data['table_data']),
                         {'page', 'sort_by', 'columns', 'data'})

    def test_page_is_an_integer_not_a_string(self):
        """`int(page)` in get_list; the Vue pager compares it numerically."""
        data = self.get_ajax('tempmon:game_list', page='1')
        self.assertEqual(data['table_data']['page'], 1)

    def test_default_sort_is_reported_back(self):
        data = self.get_ajax('tempmon:game_list')
        self.assertEqual(data['table_data']['sort_by'], '-last_played')

    def test_explicit_sort_is_reported_back(self):
        data = self.get_ajax('tempmon:game_list', sort_by='name')
        self.assertEqual(data['table_data']['sort_by'], 'name')
        names = [row['name'] for row in data['table_data']['data']]
        self.assertEqual(names, sorted(names))

    def test_descending_sort(self):
        data = self.get_ajax('tempmon:game_list', sort_by='-name')
        names = [row['name'] for row in data['table_data']['data']]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_unknown_sort_falls_back_to_the_default(self):
        """`?sort_by=nope` used to reach order_by() and raise FieldError, so
        it was a 500."""
        data = self.get_ajax('tempmon:game_list', sort_by='nope')
        self.assertEqual(data['table_data']['sort_by'], '-last_played')

    def test_relation_traversal_is_rejected(self):
        """Ordering by an undisplayed field leaks something about its
        values and forces an expensive lookup."""
        data = self.get_ajax('tempmon:game_list', sort_by='title_id')
        self.assertEqual(data['table_data']['sort_by'], '-last_played')

    def test_random_ordering_is_rejected(self):
        data = self.get_ajax('tempmon:game_list', sort_by='?')
        self.assertEqual(data['table_data']['sort_by'], '-last_played')

    def test_descending_prefix_is_allowed_on_a_real_column(self):
        data = self.get_ajax('tempmon:game_list', sort_by='-name')
        self.assertEqual(data['table_data']['sort_by'], '-name')

    def test_default_sort_is_itself_sortable(self):
        """A default that is not on its own allow-list would loop back to
        itself and quietly order by nothing sensible."""
        data = self.get_ajax('tempmon:game_list')
        sort_by = data['table_data']['sort_by']
        self.assertIsNotNone(sort_by)
        # Round-trips: asking for the default returns the default.
        again = self.get_ajax('tempmon:game_list', sort_by=sort_by)
        self.assertEqual(again['table_data']['sort_by'], sort_by)

    def test_total_results_counts_the_whole_query_not_the_page(self):
        data = self.get_ajax('tempmon:game_list')
        self.assertEqual(data['total_results'], 3)
        self.assertEqual(len(data['table_data']['data']), 3)

    def test_stats_is_a_count_and_a_timing(self):
        data = self.get_ajax('tempmon:game_list')
        count, timing = data['stats']
        self.assertEqual(count, '3 件')
        self.assertTrue(timing.startswith('Q:'))

    def test_filter_narrows_the_result(self):
        data = self.get_ajax('tempmon:game_list', Title='Beta')
        self.assertEqual(data['total_results'], 1)
        self.assertEqual(cell_text(data['table_data']['data'][0]['name']),
                         'Beta Racer')

    def test_filter_matching_nothing_returns_an_empty_page(self):
        """No rows is not the same as page-out-of-range; both must be 200."""
        data = self.get_ajax('tempmon:game_list', Title='Nonexistent')
        self.assertEqual(data['total_results'], 0)
        self.assertEqual(data['table_data']['data'], [])

    def test_page_out_of_range_returns_the_empty_envelope(self):
        """The EmptyPage branch: a degraded envelope with a *string* stat."""
        data = self.get_ajax('tempmon:game_list', page='99')
        self.assertEqual(data['total_results'], 0)
        self.assertEqual(data['table_data']['data'], [])
        self.assertEqual(data['stats'], '0 件')

    def test_page_size_is_twenty(self):
        now = timezone.now()
        for i in range(25):
            PsGame.objects.create(
                title_id=f'CUSA1{i:04}', name=f'Filler {i:02}',
                play_time=dt.timedelta(minutes=5), last_played=now)
        data = self.get_ajax('tempmon:game_list')
        self.assertEqual(data['total_results'], 28)
        self.assertEqual(len(data['table_data']['data']), 20)

        page2 = self.get_ajax('tempmon:game_list', page='2')
        self.assertEqual(len(page2['table_data']['data']), 8)


class TestAjaxColumns(AjaxListTestBase):
    """The `columns` block drives the table header and cell rendering."""

    def test_column_properties(self):
        data = self.get_ajax('tempmon:game_list')
        columns = {c['field']: c for c in data['table_data']['columns']}
        self.assertEqual(set(columns), {'name', 'last_played', 'play_time'})
        self.assertEqual(set(columns['name']),
                         {'field', 'label', 'type', 'visible', 'name'})

    def test_label_comes_from_verbose_name(self):
        """This is the column header; losing it degrades to a field name
        silently."""
        columns = {c['field']: c
                   for c in self.get_ajax('tempmon:game_list')
                   ['table_data']['columns']}
        self.assertEqual(columns['name']['label'], 'Name')
        self.assertEqual(columns['last_played']['label'], 'Last played')


class TestAjaxRowRendering(AjaxListTestBase):
    """Cell values, including the raw HTML the table injects with v-html."""

    def test_datetime_is_formatted_to_the_minute(self):
        data = self.get_ajax('tempmon:game_list', Title='Beta')
        self.assertRegex(data['table_data']['data'][0]['last_played'],
                         r'^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}$')

    def test_custom_format_callable_renders_the_duration(self):
        data = self.get_ajax('tempmon:game_list', Title='Beta')
        self.assertEqual(data['table_data']['data'][0]['play_time'], '1:30')


class TestHtmlShellContext(AjaxListTestBase):
    """The non-ajax page: filter definitions and an empty table placeholder."""

    def test_context_keys(self):
        response = self.client.get(reverse('tempmon:game_list'))
        self.assertEqual(response.status_code, 200)
        for key in ['filter_list', 'active_filters', 'table_data',
                    'list_title', 'is_mobile_card', 'FFilter']:
            self.assertIn(key, response.context)

    def test_table_data_starts_empty(self):
        """The shell ships no rows; the Vue table fetches them immediately."""
        response = self.client.get(reverse('tempmon:game_list'))
        table_data = json.loads(response.context['table_data'])
        self.assertEqual(table_data['data'], [])
        self.assertEqual(table_data['columns'], '')

    def test_filter_list_contains_every_configured_filter(self):
        response = self.client.get(reverse('tempmon:game_list'))
        filter_list = response.context['filter_list']
        for label in ['Title', 'Duration (min)']:
            self.assertIn(f"'label':'{label}'", filter_list)

    def test_active_filters_records_positions_of_applied_filters(self):
        """Indices into the filter list, used to auto-open those panels."""
        response = self.client.get(
            reverse('tempmon:game_list'), {'Title': 'Beta'})
        self.assertEqual(response.context['active_filters'], [0])

    def test_unknown_query_parameter_is_ignored(self):
        response = self.client.get(reverse('tempmon:game_list'),
                                   {'not_a_filter': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_filters'], [])

    def test_filter_value_is_echoed_back_into_the_filter_list(self):
        response = self.client.get(
            reverse('tempmon:game_list'), {'Title': 'Beta'})
        self.assertIn("'value':'Beta'", response.context['filter_list'])

    def test_list_title(self):
        response = self.client.get(reverse('tempmon:game_list'))
        self.assertEqual(response.context['list_title'], 'Game play time')


class TestTableDataUnit(TestCase):
    """`TableData` in isolation, for the branches the one remaining
    AjaxList-based list view does not reach -- and, increasingly, for
    coverage that used to only exist through a page that has since moved to
    FilteredListView. TableData itself is not going anywhere: FilteredListView
    reuses it unchanged, so none of this is at risk of going stale early."""

    fixtures = ['baseline', '閲']

    def test_string_shorthand_is_expanded_to_a_dict(self):
        table = TableData(Kotowaza, ['kotowaza', 'yomi'])
        fields = [c['field'] for c in table.get_col_template()]
        self.assertEqual(fields, ['kotowaza', 'yomi'])

    def test_field_not_on_the_model_keeps_its_name_as_label(self):
        """Annotated columns have no meta entry to read a verbose_name from."""
        table = TableData(Kotowaza, [{'name': 'computed'}])
        self.assertEqual(table.get_col_template()[0]['label'], 'computed')

    def test_traversed_field_uses_double_underscore(self):
        kanji = Kanji.objects.get(kanji='閲')
        table = TableData(Kanji, [{'name': 'kanken__kyu'}])
        self.assertEqual(table.get_table_row(kanji),
                         {'kanken__kyu': kanji.kanken.kyu})

    def test_custom_format_callable(self):
        kanji = Kanji.objects.get(kanji='閲')
        table = TableData(Kanji, [{'name': 'kanken', 'format': lambda x: str(x)[0]}])
        self.assertEqual(table.get_table_row(kanji),
                         {'kanken': str(kanji.kanken)[0]})

    def test_get_table_full_combines_columns_and_data(self):
        table = TableData(Kotowaza, ['kotowaza'])
        Kotowaza.objects.create(kotowaza='犬も歩けば棒に当たる', yomi='いぬも')
        full = table.get_table_full(Kotowaza.objects.all())
        self.assertEqual(set(full), {'columns', 'data'})
        self.assertEqual(full['data'],
                         [{'kotowaza': '犬も歩けば棒に当たる'}])

    def test_link_pk_builds_a_leading_slash_path(self):
        link = TableData.FieldProps.link_pk('example')
        kotowaza = Kotowaza.objects.create(kotowaza='猿も木から落ちる')
        self.assertEqual(link(kotowaza), f'/example/{kotowaza.pk}')

    def test_link_column_wraps_the_value_in_an_escaped_anchor(self):
        """format_html, not string concatenation (fixed alongside the first
        FilteredListView migration): the label is escaped, and the result is
        marked safe so a template can render it without a second escaping
        pass double-encoding the anchor tag itself."""
        from django.utils.safestring import SafeString

        kotowaza = Kotowaza.objects.create(kotowaza='<script>alert(1)</script>')
        table = TableData(Kotowaza, [
            {'name': 'kotowaza', 'link': TableData.FieldProps.link_pk('kotowaza')}])
        value = table.get_table_row(kotowaza)['kotowaza']
        self.assertIsInstance(value, SafeString)
        self.assertIn(f'href="/kotowaza/{kotowaza.pk}/"', value)
        self.assertNotIn('<script>', value)
        self.assertIn('&lt;script&gt;', value)

    def test_format_date_has_no_time_component(self):
        self.assertEqual(
            TableData.FieldProps.format_date(dt.date(2024, 3, 9)),
            '2024.03.09')

    def test_std_str_maps_none_to_empty(self):
        self.assertEqual(TableData.FieldProps.std_str(None), '')
        self.assertEqual(TableData.FieldProps.std_str(0), '0')

    def test_visible_defaults_true_and_can_be_overridden(self):
        table = TableData(Kotowaza, ['kotowaza',
                                     {'name': 'yomi', 'visible': False}])
        visible = {c['field']: c['visible'] for c in table.get_col_template()}
        self.assertEqual(visible, {'kotowaza': True, 'yomi': False})

    def test_boolean_field_is_typed_bool(self):
        from kukan.models import Example

        table = TableData(Example, ['is_joyo'])
        self.assertEqual(table.get_col_template()[0]['type'], 'bool')

    def test_choice_field_is_rendered_as_its_display_value(self):
        from kukan.models import Example

        example = Example.objects.create(
            word='閲する', yomi='けみする', sentence='書類を閲する',
            definition='', ex_kind=Example.KAKI, is_joyo=False)
        table = TableData(Example, ['ex_kind'])
        self.assertEqual(table.get_table_row(example)['ex_kind'], '書き取り')

    def test_boolean_value_stays_a_python_bool_not_a_string(self):
        """format_identical, not str(): a server-rendered checkbox column
        needs a real bool to branch on, same as the Vue table's v-if did."""
        from kukan.models import Example

        example = Example.objects.create(
            word='閲する', yomi='けみする', sentence='',
            definition='', ex_kind=Example.KAKI, is_joyo=False)
        table = TableData(Example, ['is_joyo'])
        self.assertIs(table.get_table_row(example)['is_joyo'], False)

    def test_numeric_field_is_typed_numeric(self):
        table = TableData(Kanji, ['strokes'])
        self.assertEqual(table.get_col_template()[0]['type'], 'numeric')

    def test_explicit_label_overrides_verbose_name(self):
        """KanjiListFilter (now on FilteredListView) annotates ex_num, which
        has no model field to read a verbose_name from -- unlike
        test_field_not_on_the_model_keeps_its_name_as_label above, this
        column supplies its own label anyway."""
        table = TableData(Kanji, [{'name': 'ex_num', 'label': '例文数'}])
        self.assertEqual(table.get_col_template()[0]['label'], '例文数')

    def test_none_renders_as_empty_string_through_a_real_row(self):
        """std_str maps None to '' so the cell is blank, not the text
        'None'."""
        kanji = Kanji.objects.get(kanji='閲')
        kanji.classification = None
        table = TableData(Kanji, ['classification'])
        self.assertEqual(table.get_table_row(kanji)['classification'], '')

    def test_foreign_key_is_stringified(self):
        kanji = Kanji.objects.get(kanji='閲')
        table = TableData(Kanji, ['kanken'])
        self.assertEqual(table.get_table_row(kanji)['kanken'],
                         str(kanji.kanken))
