"""Contract tests for `AjaxList` and `TableData`.

Seven list pages share one engine. The browser loads an HTML shell, then the
Vue table re-requests the same URL with `ajax=1` and renders whatever JSON
comes back. That JSON is an undeclared API: no serializer, no schema, just
whatever `get_list` happens to assemble.

Two reasons to pin it now rather than in Stage 9:

* Stage 10 replaces the Vue frontend with HTMX/Alpine. Whatever the new
  frontend consumes, these tests describe what the old one was given, so the
  replacement can be checked against the real shape instead of against
  somebody's memory of it.
* `TableData.FieldProps` reads `verbose_name`, `choices` and
  `get_internal_type()` off the model meta API. Those are exactly the surfaces
  Django 6.0 moves, and a change there degrades column labels and types
  silently — the page still renders, it is just wrong.

The HTML-shell path and the ajax path are tested separately because they build
their context by different routes and only the ajax one touches the database.
"""
import json
import re

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from kukan.models import Example, Kanji, Kotowaza
from kukan.views import TableData


def cell_text(value):
    """Strip the anchor that link columns wrap around their value."""
    return re.sub(r'<[^>]+>', '', value)


class AjaxListTestBase(TestCase):
    fixtures = ['baseline', '閲', '覧', '斌', '劉', '遥']

    def setUp(self):
        Example.objects.create(word='閲する', yomi='ケミスル',
                               sentence='膨大な資料を閲する', is_joyo=False)
        Example.objects.create(word='斌斌', yomi='ヒンピン',
                               sentence='恩師の斌斌たる人柄が偲ばれる', is_joyo=False)
        Example.objects.create(word='劉覧', yomi='リュウラン', sentence='劉覧',
                               is_joyo=False)
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def get_ajax(self, url_name, **params):
        params['ajax'] = '1'
        response = self.client.get(reverse(url_name), params)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)


class TestAjaxEnvelope(AjaxListTestBase):
    """The top-level shape of the ajax response, for every list view."""

    list_views = ['kukan:kanji_list', 'kukan:yoji_list', 'kukan:example_list',
                  'kukan:kotowaza_list', 'kukan:test_result_list']

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
        data = self.get_ajax('kukan:example_list', page='1')
        self.assertEqual(data['table_data']['page'], 1)

    def test_default_sort_is_reported_back(self):
        data = self.get_ajax('kukan:example_list')
        self.assertEqual(data['table_data']['sort_by'], 'kanken')

    def test_explicit_sort_is_reported_back(self):
        data = self.get_ajax('kukan:example_list', sort_by='word')
        self.assertEqual(data['table_data']['sort_by'], 'word')
        words = [cell_text(row['word']) for row in data['table_data']['data']]
        self.assertEqual(words, sorted(words))

    def test_descending_sort(self):
        data = self.get_ajax('kukan:example_list', sort_by='-word')
        words = [cell_text(row['word']) for row in data['table_data']['data']]
        self.assertEqual(words, sorted(words, reverse=True))

    def test_unknown_sort_falls_back_to_the_default(self):
        """`?sort_by=nope` used to reach order_by() and raise FieldError, so
        it was a 500."""
        data = self.get_ajax('kukan:example_list', sort_by='nope')
        self.assertEqual(data['table_data']['sort_by'], 'kanken')

    def test_relation_traversal_is_rejected(self):
        """Ordering by an undisplayed related field leaks something about its
        values and forces an expensive join."""
        data = self.get_ajax('kukan:example_list',
                             sort_by='kanjis__kanjidetails__anki_English')
        self.assertEqual(data['table_data']['sort_by'], 'kanken')

    def test_random_ordering_is_rejected(self):
        data = self.get_ajax('kukan:example_list', sort_by='?')
        self.assertEqual(data['table_data']['sort_by'], 'kanken')

    def test_descending_prefix_is_allowed_on_a_real_column(self):
        data = self.get_ajax('kukan:example_list', sort_by='-word')
        self.assertEqual(data['table_data']['sort_by'], '-word')

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
        data = self.get_ajax('kukan:example_list')
        self.assertEqual(data['total_results'], 3)
        self.assertEqual(len(data['table_data']['data']), 3)

    def test_stats_is_a_count_and_a_timing(self):
        data = self.get_ajax('kukan:example_list')
        count, timing = data['stats']
        self.assertEqual(count, '3 件')
        self.assertTrue(timing.startswith('Q:'))

    def test_filter_narrows_the_result(self):
        data = self.get_ajax('kukan:example_list', 単語='斌')
        self.assertEqual(data['total_results'], 1)
        self.assertEqual(cell_text(data['table_data']['data'][0]['word']),
                         '斌斌')

    def test_filter_matching_nothing_returns_an_empty_page(self):
        """No rows is not the same as page-out-of-range; both must be 200."""
        data = self.get_ajax('kukan:example_list', 単語='存在しない')
        self.assertEqual(data['total_results'], 0)
        self.assertEqual(data['table_data']['data'], [])

    def test_page_out_of_range_returns_the_empty_envelope(self):
        """The EmptyPage branch: a degraded envelope with a *string* stat."""
        data = self.get_ajax('kukan:example_list', page='99')
        self.assertEqual(data['total_results'], 0)
        self.assertEqual(data['table_data']['data'], [])
        self.assertEqual(data['stats'], '0 件')

    def test_page_size_is_twenty(self):
        # Words must contain a kanji from the fixture: Example.save() derives
        # kanken from the characters of `word` and raises without one.
        for i in range(25):
            Example.objects.create(word=f'閲{i:02}', yomi='エツ', sentence='',
                                   is_joyo=False)
        data = self.get_ajax('kukan:example_list')
        self.assertEqual(data['total_results'], 28)
        self.assertEqual(len(data['table_data']['data']), 20)

        page2 = self.get_ajax('kukan:example_list', page='2')
        self.assertEqual(len(page2['table_data']['data']), 8)


class TestAjaxColumns(AjaxListTestBase):
    """The `columns` block drives the table header and cell rendering."""

    def test_column_properties(self):
        data = self.get_ajax('kukan:example_list')
        columns = {c['field']: c for c in data['table_data']['columns']}
        self.assertEqual(set(columns), {'word', 'yomi', 'sentence', 'kanken',
                                        'is_joyo', 'ex_kind', 'updated_time'})
        self.assertEqual(set(columns['word']),
                         {'field', 'label', 'type', 'visible', 'name'})

    def test_label_comes_from_verbose_name(self):
        """This is the Japanese column header; losing it degrades to a field
        name silently."""
        columns = {c['field']: c
                   for c in self.get_ajax('kukan:example_list')
                   ['table_data']['columns']}
        self.assertEqual(columns['word']['label'], '単語')
        self.assertEqual(columns['sentence']['label'], '例文')
        self.assertEqual(columns['is_joyo']['label'], '常表例')

    def test_boolean_field_is_typed_bool(self):
        columns = {c['field']: c
                   for c in self.get_ajax('kukan:example_list')
                   ['table_data']['columns']}
        self.assertEqual(columns['is_joyo']['type'], 'bool')

    def test_numeric_field_is_typed_numeric(self):
        columns = {c['field']: c
                   for c in self.get_ajax('kukan:kanji_list')
                   ['table_data']['columns']}
        self.assertEqual(columns['strokes']['type'], 'numeric')

    def test_explicit_label_overrides_verbose_name(self):
        """KanjiListFilter annotates ex_num, which has no model field."""
        columns = {c['field']: c
                   for c in self.get_ajax('kukan:kanji_list')
                   ['table_data']['columns']}
        self.assertEqual(columns['ex_num']['label'], '例文数')


class TestAjaxRowRendering(AjaxListTestBase):
    """Cell values, including the raw HTML the table injects with v-html."""

    def test_boolean_stays_a_json_boolean(self):
        """format_identical, not str(): the Vue table renders a checkbox."""
        data = self.get_ajax('kukan:example_list')
        self.assertIs(data['table_data']['data'][0]['is_joyo'], False)

    def test_choice_field_is_rendered_as_its_display_value(self):
        data = self.get_ajax('kukan:example_list')
        self.assertEqual(data['table_data']['data'][0]['ex_kind'], '書き取り')

    def test_link_column_is_wrapped_in_an_anchor(self):
        """Raw HTML in the JSON. Pinned because Stage 10 has to reproduce or
        deliberately replace it."""
        data = self.get_ajax('kukan:example_list', 単語='斌')
        pk = Example.objects.get(word='斌斌').pk
        self.assertEqual(data['table_data']['data'][0]['word'],
                         f'<a href="/example/{pk}/">斌斌</a>')

    def test_foreign_key_is_stringified(self):
        data = self.get_ajax('kukan:example_list', 単語='斌')
        self.assertEqual(data['table_data']['data'][0]['kanken'], '準１級')

    def test_datetime_is_formatted_to_the_minute(self):
        data = self.get_ajax('kukan:example_list', 単語='斌')
        self.assertRegex(data['table_data']['data'][0]['updated_time'],
                         r'^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}$')

    def test_none_renders_as_empty_string(self):
        """std_str maps None to '' so the cell is blank, not the text 'None'."""
        Kanji.objects.filter(kanji='閲').update(classification=None)
        data = self.get_ajax('kukan:kanji_list', 漢字='閲')
        self.assertEqual(data['table_data']['data'][0]['classification'], '')


class TestHtmlShellContext(AjaxListTestBase):
    """The non-ajax page: filter definitions and an empty table placeholder."""

    def test_context_keys(self):
        response = self.client.get(reverse('kukan:example_list'))
        self.assertEqual(response.status_code, 200)
        for key in ['filter_list', 'active_filters', 'table_data',
                    'list_title', 'is_mobile_card', 'FFilter']:
            self.assertIn(key, response.context)

    def test_table_data_starts_empty(self):
        """The shell ships no rows; the Vue table fetches them immediately."""
        response = self.client.get(reverse('kukan:example_list'))
        table_data = json.loads(response.context['table_data'])
        self.assertEqual(table_data['data'], [])
        self.assertEqual(table_data['columns'], '')

    def test_filter_list_contains_every_configured_filter(self):
        response = self.client.get(reverse('kukan:example_list'))
        filter_list = response.context['filter_list']
        for label in ['単語', '漢検', '種類', '例文', '作成', '変更', '意味']:
            self.assertIn(f"'label':'{label}'", filter_list)

    def test_active_filters_records_positions_of_applied_filters(self):
        """Indices into the filter list, used to auto-open those panels."""
        response = self.client.get(reverse('kukan:example_list'), {'単語': '斌'})
        self.assertEqual(response.context['active_filters'], [0])

    def test_unknown_query_parameter_is_ignored(self):
        response = self.client.get(reverse('kukan:example_list'),
                                   {'not_a_filter': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_filters'], [])

    def test_filter_value_is_echoed_back_into_the_filter_list(self):
        response = self.client.get(reverse('kukan:example_list'), {'単語': '斌'})
        self.assertIn("'value':'%E6%96%8C'", response.context['filter_list'])

    def test_list_title(self):
        response = self.client.get(reverse('kukan:example_list'))
        self.assertEqual(response.context['list_title'], '例文')


class TestTableDataUnit(TestCase):
    """`TableData` in isolation, for the branches the list views do not reach."""

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

    def test_format_date_has_no_time_component(self):
        import datetime as dt
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
