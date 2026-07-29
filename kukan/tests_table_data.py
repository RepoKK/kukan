"""Contract tests for `TableData`.

`TableData` renders a model queryset into the column template and row dicts
that `kukan/templates/ui/_table.html` walks. `AjaxList` -- the Vue-era view
that serialised the same structure to JSON -- is gone; `TableData` is not,
because `FilteredListView` reuses it unchanged.

Worth pinning because `TableData.FieldProps` reads `verbose_name`, `choices`
and `get_internal_type()` off the model meta API. Those are exactly the
surfaces Django moves between releases, and a change there degrades column
labels and types silently: the page still renders, it is just wrong.

These are deliberately unit-level. The same coverage used to live behind
whichever list view happened to exercise the branch, which meant it moved or
broke every time a page was migrated.
"""
import datetime as dt

from django.test import TestCase

from kukan.models import Kanji, Kotowaza
from kukan.views import TableData


class TestTableDataUnit(TestCase):
    """Column templates and row rendering, straight off the class."""

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
