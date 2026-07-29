"""Contract tests for `FilteredListView`, exercised through `KotowazaList` and
`YojiList` -- the first two of the seven list pages moved off `AjaxList`.

This is the frontend rewrite's actual regression net for list views: PKs,
ordering and page count through the real view, not a golden-diff of HTML.
`kukan.tests_ajax_list` keeps covering `AjaxList`/`TableData` for the list
pages not yet migrated.
"""
from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import Client, TestCase
from django.urls import reverse

from kukan.models import Kotowaza, Yoji


class KotowazaListContractTest(TestCase):
    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')

    def test_requires_login(self):
        response = Client().get(reverse('kukan:kotowaza_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_a_normal_request_renders_the_full_page(self):
        response = self.client.get(reverse('kukan:kotowaza_list'))
        self.assertContains(response, 'navbar-burger')
        self.assertContains(response, '<table')

    def test_an_htmx_request_renders_only_the_table_partial(self):
        response = self.client.get(
            reverse('kukan:kotowaza_list'), HTTP_HX_REQUEST='true')
        self.assertNotContains(response, 'navbar-burger')
        self.assertContains(response, '<table')
        self.assertContains(response, 'id="results"')

    def test_no_vue_or_buefy_remains(self):
        response = self.client.get(reverse('kukan:kotowaza_list'))
        content = response.content.decode()
        self.assertNotIn('vue_app', content)
        self.assertNotIn('buefy', content.lower())
        self.assertNotIn('v-filter', content)

    def test_default_sort_is_by_kotowaza(self):
        Kotowaza.objects.create(kotowaza='2番目')
        Kotowaza.objects.create(kotowaza='1番目')
        response = self.client.get(reverse('kukan:kotowaza_list'))
        self.assertEqual(
            [k.kotowaza for k in response.context['object_list']],
            ['1番目', '2番目'])

    def test_sort_by_is_honoured(self):
        Kotowaza.objects.create(kotowaza='2番目')
        Kotowaza.objects.create(kotowaza='1番目')
        response = self.client.get(
            reverse('kukan:kotowaza_list'), {'sort_by': '-kotowaza'})
        self.assertEqual(
            [k.kotowaza for k in response.context['object_list']],
            ['2番目', '1番目'])

    def test_unknown_sort_by_falls_back_to_the_default(self):
        """`?sort_by=nope` used to reach order_by() directly and 500."""
        response = self.client.get(
            reverse('kukan:kotowaza_list'), {'sort_by': 'nope'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sort_by'], 'kotowaza')

    def test_filter_narrows_the_result_by_pk(self):
        keep = Kotowaza.objects.create(kotowaza='犬も歩けば棒に当たる')
        Kotowaza.objects.create(kotowaza='猿も木から落ちる')
        response = self.client.get(
            reverse('kukan:kotowaza_list'), {'諺': '犬'})
        self.assertEqual(
            {k.pk for k in response.context['object_list']}, {keep.pk})

    def test_filter_value_is_echoed_back_into_the_input(self):
        response = self.client.get(
            reverse('kukan:kotowaza_list'), {'諺': '犬'})
        self.assertContains(response, 'name="諺" value="犬"')

    def test_page_size_is_twenty(self):
        for i in range(25):
            Kotowaza.objects.create(kotowaza=f'諺{i:02}')
        response = self.client.get(reverse('kukan:kotowaza_list'))
        self.assertEqual(len(response.context['object_list']), 20)
        self.assertEqual(response.context['page_obj'].paginator.count, 25)

        page2 = self.client.get(
            reverse('kukan:kotowaza_list'), {'page': 2})
        self.assertEqual(len(page2.context['object_list']), 5)

    def test_a_page_link_preserves_the_active_filter(self):
        """Sort/page links are self-contained URLs (query_string_replace),
        not hx-include -- this is the test that catches losing a filter
        value on the second page."""
        for i in range(25):
            Kotowaza.objects.create(kotowaza=f'犬{i:02}')
        Kotowaza.objects.create(kotowaza='猿も木から落ちる')
        response = self.client.get(
            reverse('kukan:kotowaza_list'), {'諺': '犬'})
        self.assertContains(response, 'page=2')
        self.assertContains(response, '%E7%8A%AC')  # 犬, percent-encoded

    def test_sort_link_toggles_direction(self):
        response = self.client.get(reverse('kukan:kotowaza_list'))
        self.assertContains(response, 'sort_by=-kotowaza')

    def test_empty_result_says_so_rather_than_an_empty_table(self):
        response = self.client.get(
            reverse('kukan:kotowaza_list'), {'諺': '絶対に存在しない諺'})
        self.assertContains(response, '結果ありません')


class YojiListContractTest(TestCase):
    """YojiList: the second page moved off AjaxList, and the first with more
    than one filter kind (string, yomi-simple, checkbox, yes/no) plus a
    per-row cell override (the 日課/anki-toggle widget)."""

    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')
        self.eturan = Yoji.objects.create(
            yoji='閲覧', reading='えつらん', meaning='しらべ見ること')
        self.shinkan = Yoji.objects.create(
            yoji='覧閲', reading='らんえつ', meaning='ためしに作った語')

    def test_a_normal_request_renders_the_full_page(self):
        response = self.client.get(reverse('kukan:yoji_list'))
        self.assertContains(response, 'navbar-burger')
        self.assertContains(response, '<table')

    def test_no_vue_or_buefy_remains(self):
        response = self.client.get(reverse('kukan:yoji_list'))
        content = response.content.decode()
        self.assertNotIn('vue_app', content)
        self.assertNotIn('buefy', content.lower())
        self.assertNotIn('v-filter', content)
        self.assertNotIn('<fr-addrem-anki', content)

    def test_string_filter_narrows_by_pk(self):
        response = self.client.get(
            reverse('kukan:yoji_list'), {'漢字': '閲覧'})
        self.assertEqual(
            {y.pk for y in response.context['object_list']}, {self.eturan.pk})

    def test_yomi_simple_filter_narrows_by_pk(self):
        response = self.client.get(
            reverse('kukan:yoji_list'), {'読み': 'えつらん_位致'})
        self.assertEqual(
            {y.pk for y in response.context['object_list']}, {self.eturan.pk})

    def test_yes_no_filter_narrows_by_pk(self):
        self.eturan.in_anki = True
        self.eturan.save()
        response = self.client.get(
            reverse('kukan:yoji_list'), {'日課': '日課に出る'})
        self.assertEqual(
            {y.pk for y in response.context['object_list']}, {self.eturan.pk})

    def test_the_anki_toggle_cell_override_renders_per_row(self):
        """The 日課 column shows the Alpine widget, not a plain checkmark --
        the cell_overrides escape hatch is what makes that possible."""
        response = self.client.get(reverse('kukan:yoji_list'))
        content = response.content.decode()
        self.assertIn(reverse('kukan:yoji_anki'), content)
        self.assertIn("body.set('yoji', '閲覧')", content)
        self.assertIn("body.set('yoji', '覧閲')", content)

    def test_the_edit_toggle_switch_is_present(self):
        response = self.client.get(reverse('kukan:yoji_list'))
        self.assertContains(response, '一覧編集可能')
        self.assertContains(response, 'editEnabled')


class ExampleListContractTest(TestCase):
    """ExampleList: the third page moved off AjaxList, needing string,
    checkbox, yes/no and daterange -- no new filter kind, but the first page
    to combine all four."""

    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        from kukan.models import Example

        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')
        self.kemisuru = Example.objects.create(
            word='閲する', yomi='けみする', sentence='書類を閲する',
            definition='調べ確かめる', ex_kind=Example.KAKI, is_joyo=False)
        self.ranran = Example.objects.create(
            word='覧覧', yomi='らんらん', sentence='',
            definition='', ex_kind=Example.YOMI, is_joyo=True)

    def test_a_normal_request_renders_the_full_page(self):
        response = self.client.get(reverse('kukan:example_list'))
        self.assertContains(response, 'navbar-burger')
        self.assertContains(response, '<table')

    def test_no_vue_or_buefy_remains(self):
        response = self.client.get(reverse('kukan:example_list'))
        content = response.content.decode()
        self.assertNotIn('vue_app', content)
        self.assertNotIn('buefy', content.lower())
        self.assertNotIn('v-filter', content)

    def test_string_filter_narrows_by_pk(self):
        response = self.client.get(
            reverse('kukan:example_list'), {'単語': '閲する'})
        self.assertEqual(
            {e.pk for e in response.context['object_list']},
            {self.kemisuru.pk})

    def test_checkbox_filter_narrows_by_pk(self):
        """FGenericCheckbox.get_choices() lists the raw stored values
        (values('ex_kind')), not their display text -- 'YOMI', not '読み'."""
        response = self.client.get(
            reverse('kukan:example_list'), {'種類': 'YOMI'})
        self.assertEqual(
            {e.pk for e in response.context['object_list']},
            {self.ranran.pk})

    def test_yes_no_filter_narrows_by_pk(self):
        response = self.client.get(
            reverse('kukan:example_list'), {'例文': '例文有り'})
        self.assertEqual(
            {e.pk for e in response.context['object_list']},
            {self.kemisuru.pk})

    def test_boolean_column_renders_a_checkmark_not_true_false(self):
        response = self.client.get(reverse('kukan:example_list'))
        content = response.content.decode()
        self.assertIn('mdi-check', content)
        self.assertNotIn('>True<', content)
        self.assertNotIn('>False<', content)

    def test_special_characters_in_a_filter_value_round_trip_safely(self):
        """The historical regression this replaces (kukan.tests.TestFilters,
        issue #12) was quotes and JS-special characters breaking
        FFilter.to_json() -- a hand-built, single-quoted JS object literal,
        not valid JSON. That mechanism is gone for this page: the value now
        lands in an HTML attribute through Django's own autoescaping, which
        is safe against this class of bug by construction rather than by
        care taken in a hand-rolled serialiser. Asserted against Django's
        own escape() rather than a hand-picked expected string, so this
        tracks the real behaviour rather than assuming it."""
        from django.utils.html import escape

        for value in ['ABC DEF', "A', 'yomi'",
                      r'",/?:@&=+$#()!`~^[]|_/\\*.',
                      'Test "#$%&\'()"']:
            with self.subTest(value=value):
                response = self.client.get(
                    reverse('kukan:example_list'), {'意味': value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response, f'name="意味" value="{escape(value)}"')


class UtilTagsTest(TestCase):
    """The two template helpers FilteredListView's rendering depends on."""

    def test_get_item_looks_up_a_dynamic_key(self):
        html = Template(
            "{% load util_tags %}{{ row|get_item:key }}"
        ).render(Context({'row': {'諺': 'value'}, 'key': '諺'}))
        self.assertEqual(html, 'value')

    def test_get_item_defaults_to_empty_string(self):
        html = Template(
            "{% load util_tags %}[{{ row|get_item:'missing' }}]"
        ).render(Context({'row': {}}))
        self.assertEqual(html, '[]')

    def test_query_string_replace_merges_into_the_existing_query(self):
        from django.test import RequestFactory
        request = RequestFactory().get('/kotowaza/list/?諺=犬')
        html = Template(
            "{% load util_tags %}{% query_string_replace request page=2 %}"
        ).render(Context({'request': request}))
        self.assertIn('page=2', html)
        self.assertIn('%E8%AB%BA=%E7%8A%AC', html)  # 諺=犬, percent-encoded

    def test_query_string_replace_overrides_an_existing_key(self):
        from django.test import RequestFactory
        request = RequestFactory().get('/kotowaza/list/?page=1')
        html = Template(
            "{% load util_tags %}{% query_string_replace request page=3 %}"
        ).render(Context({'request': request}))
        self.assertEqual(html, 'page=3')
