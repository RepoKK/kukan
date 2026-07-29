"""Contract tests for the kanji detail page.

PLAN.md calls this one of the hard pages, because of the tabs: one tab per
category that has any rows, each with its own table and its own paging. In
Vue that was a `b-tabs` over a `v-for` fed by a `json.dumps` blob; here the
view hands over real objects and the template renders every tab, with Alpine
holding two integers.

It is also the page that renders the HTML-emitting model methods, which is
why `tests_models.HtmlEmittingModelMethodsTest` exists.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from kukan.models import Example, ExMap, Kanji, Yoji


class KanjiDetailTest(TestCase):
    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')
        self.kanji = Kanji.objects.get(kanji='閲')

    def add_examples(self, count, kind=None, sentence='資料を閲覧する'):
        made = []
        for i in range(count):
            example = Example.objects.create(
                word=f'閲覧{i}', yomi='えつらん', sentence=sentence,
                definition='', is_joyo=False,
                **({'ex_kind': kind} if kind else {}))
            ExMap.objects.create(example=example, kanji=self.kanji,
                                 is_ateji=False, in_joyo_list=True,
                                 map_order=i)
            made.append(example)
        return made

    def get(self):
        response = self.client.get(
            reverse('kukan:kanji_detail', args=[self.kanji.kanji]))
        self.assertEqual(response.status_code, 200)
        return response

    def categories(self):
        return {c['name']: c for c in self.get().context['categories']}

    def test_requires_login(self):
        response = Client().get(
            reverse('kukan:kanji_detail', args=[self.kanji.kanji]))
        self.assertEqual(response.status_code, 302)

    def test_no_vue_or_buefy_remains(self):
        content = self.get().content.decode()
        for marker in ['vue_app', 'b-tabs', 'b-tab-item', 'b-table',
                       'fr-kanji-box', 'slot-scope', 'v-for', 'v-html',
                       'node_modules', '[[']:
            self.assertNotIn(marker, content, f'{marker} still on the page')

    def test_a_category_with_no_rows_gets_no_tab(self):
        """The tabs are per-category-with-content, so a kanji with no 諺 has
        no 諺 tab rather than an empty one."""
        self.add_examples(1)
        self.assertEqual(set(self.categories()), {'例文'})

    def test_each_category_with_rows_gets_a_tab(self):
        self.add_examples(1)
        Yoji.objects.create(yoji='閲覧注意', reading='えつらんちゅうい',
                            meaning='...')
        self.assertEqual(set(self.categories()), {'例文', '四字熟語'})

    def test_the_tab_count_is_the_row_count(self):
        self.add_examples(3)
        self.assertEqual(self.categories()['例文']['number'], 3)
        self.assertContains(self.get(), 'is-rounded')

    def test_rows_are_sliced_into_pages_of_five(self):
        """Buefy paginated at 5 per page once there were more than 5."""
        self.add_examples(7)
        pages = self.categories()['例文']['pages']
        self.assertEqual([len(p) for p in pages], [5, 2])

    def test_a_short_category_is_a_single_page_with_no_pagination(self):
        self.add_examples(3)
        self.assertEqual(len(self.categories()['例文']['pages']), 1)
        self.assertNotContains(self.get(), 'pagination-link')

    def test_a_long_category_renders_pagination_links(self):
        self.add_examples(7)
        response = self.get()
        self.assertContains(response, 'pagination-link')
        self.assertContains(response, '@click="page = 1"')

    def test_every_row_is_in_the_dom_not_just_the_first_page(self):
        """Paging is Alpine hiding tbodies, so page 2 is already there --
        this is what makes it safe to have no server round-trip."""
        self.add_examples(7)
        response = self.get()
        for i in range(7):
            self.assertContains(response, f'閲覧{i}')

    def test_switching_tab_resets_the_page(self):
        self.add_examples(7)
        Yoji.objects.create(yoji='閲覧注意', reading='えつらんちゅうい',
                            meaning='...')
        self.assertContains(self.get(), 'tab = 1; page = 0')

    def test_example_words_link_to_their_detail_page(self):
        example = self.add_examples(1)[0]
        self.assertContains(self.get(), f'href="/example/{example.pk}/"')

    def test_readings_render_their_example_anchors_as_links(self):
        """`Reading.get_list_ex2` returns markup. If it stopped being marked
        safe, this is where it would show up as visible `&lt;a href=`."""
        example = self.add_examples(1)[0]
        reading = self.kanji.reading_set.first()
        ExMap.objects.filter(example=example).update(reading=reading)
        response = self.get()
        self.assertContains(response, f'<a href="/example/{example.pk}/">')
        self.assertNotContains(response, '&lt;a href=')

    def test_the_attributes_table_has_no_none_row(self):
        """`basic_info2` used to append a row labelled `None` for any kanji
        with no variant form."""
        response = self.get()
        self.assertContains(response, '属性')
        self.assertNotContains(response, '<th>None</th>')

    def test_the_external_dictionary_link_is_a_real_anchor(self):
        self.assertContains(self.get(), '>漢字辞典オンライン</a>')

    def test_the_kanji_box_starts_on_the_kanji_itself(self):
        self.assertContains(self.get(), "current: '閲'")

    def test_a_kanji_with_no_variants_has_no_variant_switcher(self):
        self.assertNotContains(self.get(), '標準字体')

    def test_a_kanji_with_variants_can_switch_between_them(self):
        variant = Kanji.objects.get(kanji='覧')
        variant.kanjidetails.std_kanji = self.kanji
        variant.kanjidetails.save()
        response = self.get()
        self.assertContains(response, '標準字体')
        self.assertContains(response, "current = '覧'")

    def test_a_bool_column_renders_a_check_icon_not_the_word_true(self):
        self.add_examples(1)
        response = self.get()
        self.assertNotContains(response, '>True<')
        self.assertNotContains(response, '>False<')
