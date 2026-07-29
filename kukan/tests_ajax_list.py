"""Contract tests for `AjaxList` and `TableData`.

kanji_list and test_result_list are the two list pages still on `AjaxList`
(kotowaza_list, yoji_list and example_list have moved to `FilteredListView` --
see `kukan.tests_listview`). The browser loads an HTML shell, then the Vue
table re-requests the same URL with `?ajax=1` and renders whatever JSON comes
back. That JSON is an undeclared API: no serializer, no schema, just whatever
`get_list` happens to assemble.

Two reasons to pin it:

* Whatever the HTMX/Alpine rewrite consumes for these two remaining pages,
  this describes what the Vue frontend was given, so the replacement can be
  checked against the real shape instead of against somebody's memory of it.
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

from kukan.models import Kanji, Kanken, Kotowaza, TestResult, TestSource
from kukan.views import TableData


def cell_text(value):
    """Strip the anchor that link columns wrap around their value."""
    return re.sub(r'<[^>]+>', '', value)


class AjaxListTestBase(TestCase):
    fixtures = ['baseline', '閲', '覧', '斌', '劉', '遥']

    def setUp(self):
        source = TestSource.objects.create(series='漢検過去問題集', kyu='2級', year='2024')
        kanken = Kanken.objects.get(kyu='２級')
        TestResult.objects.create(kanken=kanken, source=source, name='OGU',
                                  test_number=1, date=dt.date(2024, 1, 5))
        TestResult.objects.create(kanken=kanken, source=source, name='COGU',
                                  test_number=2, date=dt.date(2024, 2, 10))
        TestResult.objects.create(kanken=kanken, source=source, name='OGU',
                                  test_number=3, date=dt.date(2024, 3, 15))
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def get_ajax(self, url_name, **params):
        params['ajax'] = '1'
        response = self.client.get(reverse(url_name), params)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)


class TestAjaxEnvelope(AjaxListTestBase):
    """The top-level shape of the ajax response, for every remaining view.

    kukan:kanji_list moved to FilteredListView too (kanji_list was the last
    and hardest of the five kukan list pages -- every filter kind, plus a
    custom get_queryset() for its ex_num annotation -- see
    kukan.tests_listview.KanjiListFilterContractTest). kukan:test_result_list
    is now the sole real view left on AjaxList.
    """

    list_views = ['kukan:test_result_list']

    def test_envelope_keys(self):
        for name in self.list_views:
            with self.subTest(view=name):
                data = self.get_ajax(name)
                self.assertEqual(set(data), {'total_results', 'table_data',
                                             'stats'})
                self.assertEqual(set(data['table_data']),
                                 {'page', 'sort_by', 'columns', 'data'})

    def test_page_is_an_integer_not_a_string(self):
        """`int(page)` in get_list; the Vue pager compares it numerically."""
        data = self.get_ajax('kukan:test_result_list', page='1')
        self.assertEqual(data['table_data']['page'], 1)

    def test_default_sort_is_reported_back(self):
        data = self.get_ajax('kukan:test_result_list')
        self.assertEqual(data['table_data']['sort_by'], '-date')

    def test_explicit_sort_is_reported_back(self):
        data = self.get_ajax('kukan:test_result_list', sort_by='test_number')
        self.assertEqual(data['table_data']['sort_by'], 'test_number')
        numbers = [row['test_number'] for row in data['table_data']['data']]
        self.assertEqual(numbers, sorted(numbers))

    def test_descending_sort(self):
        data = self.get_ajax('kukan:test_result_list', sort_by='-test_number')
        numbers = [row['test_number'] for row in data['table_data']['data']]
        self.assertEqual(numbers, sorted(numbers, reverse=True))

    def test_unknown_sort_falls_back_to_the_default(self):
        """`?sort_by=nope` used to reach order_by() and raise FieldError, so
        it was a 500."""
        data = self.get_ajax('kukan:test_result_list', sort_by='nope')
        self.assertEqual(data['table_data']['sort_by'], '-date')

    def test_relation_traversal_is_rejected(self):
        """Ordering by an undisplayed related field leaks something about its
        values and forces an expensive join."""
        data = self.get_ajax('kukan:test_result_list',
                             sort_by='kanken__item_01_name')
        self.assertEqual(data['table_data']['sort_by'], '-date')

    def test_random_ordering_is_rejected(self):
        data = self.get_ajax('kukan:test_result_list', sort_by='?')
        self.assertEqual(data['table_data']['sort_by'], '-date')

    def test_descending_prefix_is_allowed_on_a_real_column(self):
        data = self.get_ajax('kukan:test_result_list', sort_by='-test_number')
        self.assertEqual(data['table_data']['sort_by'], '-test_number')

    def test_every_list_default_sort_is_itself_sortable(self):
        """A default that is not on its own allow-list would loop back to
        itself and quietly order by nothing sensible."""
        for name in self.list_views:
            with self.subTest(view=name):
                data = self.get_ajax(name)
                sort_by = data['table_data']['sort_by']
                self.assertIsNotNone(sort_by)
                # Round-trips: asking for the default returns the default.
                again = self.get_ajax(name, sort_by=sort_by)
                self.assertEqual(again['table_data']['sort_by'], sort_by)

    def test_total_results_counts_the_whole_query_not_the_page(self):
        data = self.get_ajax('kukan:test_result_list')
        self.assertEqual(data['total_results'], 3)
        self.assertEqual(len(data['table_data']['data']), 3)

    def test_stats_is_a_count_and_a_timing(self):
        data = self.get_ajax('kukan:test_result_list')
        count, timing = data['stats']
        self.assertEqual(count, '3 件')
        self.assertTrue(timing.startswith('Q:'))

    def test_filter_narrows_the_result(self):
        data = self.get_ajax('kukan:test_result_list', 名前='COGU')
        self.assertEqual(data['total_results'], 1)
        # std_str applies regardless of type -- only BooleanField columns get
        # format_identical, so a numeric column still renders as a string.
        self.assertEqual(data['table_data']['data'][0]['test_number'], '2')

    def test_filter_matching_nothing_returns_an_empty_page(self):
        """No rows is not the same as page-out-of-range; both must be 200."""
        data = self.get_ajax('kukan:test_result_list', 問題番号='999')
        self.assertEqual(data['total_results'], 0)
        self.assertEqual(data['table_data']['data'], [])

    def test_page_out_of_range_returns_the_empty_envelope(self):
        """The EmptyPage branch: a degraded envelope with a *string* stat."""
        data = self.get_ajax('kukan:test_result_list', page='99')
        self.assertEqual(data['total_results'], 0)
        self.assertEqual(data['table_data']['data'], [])
        self.assertEqual(data['stats'], '0 件')

    def test_page_size_is_twenty(self):
        source = TestSource.objects.get()
        kanken = Kanken.objects.get(kyu='２級')
        for i in range(25):
            TestResult.objects.create(
                kanken=kanken, source=source, name='OGU',
                test_number=100 + i, date=dt.date(2024, 6, 1))
        data = self.get_ajax('kukan:test_result_list')
        self.assertEqual(data['total_results'], 28)
        self.assertEqual(len(data['table_data']['data']), 20)

        page2 = self.get_ajax('kukan:test_result_list', page='2')
        self.assertEqual(len(page2['table_data']['data']), 8)


class TestAjaxColumns(AjaxListTestBase):
    """The `columns` block drives the table header and cell rendering."""

    def test_column_properties(self):
        data = self.get_ajax('kukan:test_result_list')
        columns = {c['field']: c for c in data['table_data']['columns']}
        self.assertIn('name', columns)
        self.assertEqual(set(columns['name']),
                         {'field', 'label', 'type', 'visible', 'name'})

    def test_label_comes_from_verbose_name(self):
        """This is the Japanese column header; losing it degrades to a field
        name silently."""
        columns = {c['field']: c
                   for c in self.get_ajax('kukan:test_result_list')
                   ['table_data']['columns']}
        self.assertEqual(columns['name']['label'], '名前')
        self.assertEqual(columns['date']['label'], '日付')

class TestAjaxRowRendering(AjaxListTestBase):
    """Cell values, including the raw HTML the table injects with v-html."""

    def test_choice_field_is_rendered_as_its_display_value(self):
        data = self.get_ajax('kukan:test_result_list', 名前='OGU')
        self.assertEqual(data['table_data']['data'][0]['name'], '大具')

    def test_foreign_key_is_stringified(self):
        data = self.get_ajax('kukan:test_result_list')
        self.assertEqual(data['table_data']['data'][0]['kanken'], '２級')

    def test_date_is_formatted_without_a_time_component(self):
        data = self.get_ajax('kukan:test_result_list', 問題番号='1')
        self.assertEqual(data['table_data']['data'][0]['date'], '2024.01.05')

class TestHtmlShellContext(AjaxListTestBase):
    """The non-ajax page: filter definitions and an empty table placeholder."""

    def test_context_keys(self):
        response = self.client.get(reverse('kukan:test_result_list'))
        self.assertEqual(response.status_code, 200)
        for key in ['filter_list', 'active_filters', 'table_data',
                    'list_title', 'is_mobile_card', 'FFilter']:
            self.assertIn(key, response.context)

    def test_table_data_starts_empty(self):
        """The shell ships no rows; the Vue table fetches them immediately."""
        response = self.client.get(reverse('kukan:test_result_list'))
        table_data = json.loads(response.context['table_data'])
        self.assertEqual(table_data['data'], [])
        self.assertEqual(table_data['columns'], '')

    def test_filter_list_contains_every_configured_filter(self):
        response = self.client.get(reverse('kukan:test_result_list'))
        filter_list = response.context['filter_list']
        for label in ['名前', '漢検', '問題集', '問題番号', '日付']:
            self.assertIn(f"'label':'{label}'", filter_list)

    def test_active_filters_records_positions_of_applied_filters(self):
        """Indices into the filter list, used to auto-open those panels."""
        response = self.client.get(
            reverse('kukan:test_result_list'), {'名前': 'OGU'})
        self.assertEqual(response.context['active_filters'], [0])

    def test_unknown_query_parameter_is_ignored(self):
        response = self.client.get(reverse('kukan:test_result_list'),
                                   {'not_a_filter': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_filters'], [])

    def test_filter_value_is_echoed_back_into_the_filter_list(self):
        response = self.client.get(
            reverse('kukan:test_result_list'), {'名前': 'OGU'})
        self.assertIn("'value':'OGU'", response.context['filter_list'])

    def test_list_title(self):
        response = self.client.get(reverse('kukan:test_result_list'))
        self.assertEqual(response.context['list_title'], 'LIST_TITLE')


class TestTableDataUnit(TestCase):
    """`TableData` in isolation, for the branches the two remaining
    AjaxList-based list views do not reach -- and, increasingly, for
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
        """Used to only be reachable through kanji_list's ajax envelope;
        kanji_list has since moved to FilteredListView."""
        table = TableData(Kanji, ['strokes'])
        self.assertEqual(table.get_col_template()[0]['type'], 'numeric')

    def test_explicit_label_overrides_verbose_name(self):
        """KanjiListFilter annotates ex_num, which has no model field to read
        a verbose_name from -- unlike test_field_not_on_the_model_keeps_its
        _name_as_label above, this column supplies its own label anyway."""
        table = TableData(Kanji, [{'name': 'ex_num', 'label': '例文数'}])
        self.assertEqual(table.get_col_template()[0]['label'], '例文数')

    def test_none_renders_as_empty_string_through_a_real_row(self):
        """std_str maps None to '' so the cell is blank, not the text
        'None'. Used to only be reachable through kanji_list's ajax
        envelope, with classification forced to None on a fixture row;
        exercised directly against TableData here instead."""
        kanji = Kanji.objects.get(kanji='閲')
        kanji.classification = None
        table = TableData(Kanji, ['classification'])
        self.assertEqual(table.get_table_row(kanji)['classification'], '')
