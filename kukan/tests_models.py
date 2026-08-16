"""Tests for the model methods that render markup and derive fields.

Two themes, both aimed squarely at later stages.

**Raw HTML.** A dozen model methods build HTML by string concatenation and
return it without `mark_safe`. Nothing escapes today because every page renders
through Vue's `v-html`, which injects the string as markup. The moment a page
is server-rendered — which is the whole of Stage 10 — Django's autoescaping
turns those into visible `&lt;a href=...&gt;` text. The tests below pin the
exact strings so the port has a reference, and so the change is a visible test
failure rather than a page that merely looks wrong.

Note also that several of these interpolate user-supplied text (`word`,
`definition`) straight into HTML with no escaping. That is latent, not live,
for the same reason. It becomes an XSS question as soon as the markup reaches a
context that trusts it differently, and the affected methods are called out
individually below.

**Derived fields.** `Example.save`, `Yoji.save` and `TestResult.save` compute a
field on every write — kanken level, cloze pattern, total score. Those are
ordinary Python and ORM aggregates that the Django 6 upgrade touches.
"""
import datetime as dt

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils.safestring import SafeString

from kukan.models import (
    Bunrui,
    Example,
    ExMap,
    Kanji,
    Kanken,
    Kotowaza,
    Reading,
    TestResult,
    TestSource,
    Yoji,
    YomiJoyo,
)


class ReadingRenderingTest(TestCase):
    """`Reading` renders okurigana and joyo markers into HTML."""

    fixtures = ['baseline', '閲']

    def get_reading(self, text):
        return Reading.objects.get(kanji='閲', reading=text)

    def test_get_simple_strips_okurigana_parentheses(self):
        self.assertEqual(self.get_reading('けみ（する）').get_simple(), 'けみする')

    def test_get_simple_leaves_a_plain_reading_alone(self):
        self.assertEqual(self.get_reading('エツ').get_simple(), 'エツ')

    def test_reading_simple_is_derived_on_save_and_folded_to_hiragana(self):
        """The FYomi filter searches this column, so katakana readings have to
        be stored folded."""
        self.assertEqual(self.get_reading('エツ').reading_simple, 'えつ')

    def test_get_full_marks_hyogai_with_a_cross(self):
        reading = self.get_reading('けみ（する）')
        reading.joyo = YomiJoyo.objects.get(yomi_joyo='表外')
        self.assertEqual(reading.get_full(), '✘ けみ（する）')

    def test_get_full_marks_special_joyo_with_a_triangle(self):
        reading = self.get_reading('エツ')
        reading.joyo = YomiJoyo.objects.get(yomi_joyo='常用・特別')
        self.assertEqual(reading.get_full(), '▽エツ')

    def test_get_full_leaves_ordinary_joyo_unmarked(self):
        self.assertEqual(self.get_reading('エツ').get_full(), 'エツ')

    def test_get_html_format_wraps_okurigana_in_a_span(self):
        """RAW HTML. Rendered through v-html today.

        The fixture's けみ（する） is 表外, so the joyo class is set explicitly
        here to isolate the span from the marker prefix.
        """
        reading = self.get_reading('けみ（する）')
        reading.joyo = YomiJoyo.objects.get(yomi_joyo='常用')
        self.assertEqual(reading.get_html_format(),
                         "けみ<span class='okuri'>する</span>")

    def test_get_html_format_combines_marker_and_span(self):
        reading = self.get_reading('けみ（する）')
        reading.joyo = YomiJoyo.objects.get(yomi_joyo='表外')
        self.assertEqual(reading.get_html_format(),
                         "✘ けみ<span class='okuri'>する</span>")

    def test_is_joyo(self):
        reading = self.get_reading('エツ')
        self.assertTrue(reading.is_joyo())
        reading.joyo = YomiJoyo.objects.get(yomi_joyo='表外')
        self.assertFalse(reading.is_joyo())


class ExampleRenderingTest(TestCase):
    """`Example` builds anchors for the kanji detail page and for Anki."""

    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        self.example = Example.objects.create(
            word='閲覧', yomi='エツラン', sentence='資料を閲覧する',
            definition='調べ見ること', is_joyo=False)

    def test_get_url_is_an_anchor_to_the_detail_page(self):
        self.assertEqual(
            self.example.get_url(),
            f'<a href="/example/{self.example.pk}/">閲覧</a>')

    def test_goo_link_points_at_the_dictionary(self):
        self.assertEqual(
            self.example.goo_link(),
            '<a href="https://dictionary.goo.ne.jp/srch/all/閲覧/m0u/">閲覧</a>')

    def test_goo_link_strips_parenthesised_suffix_from_the_url_only(self):
        """'閲覧（する）' searches for 閲覧 but still displays the full word."""
        self.example.word = '閲覧（する）'
        link = self.example.goo_link()
        self.assertIn('/srch/all/閲覧/m0u/', link)
        self.assertIn('>閲覧（する）</a>', link)

    def test_goo_link_is_empty_without_a_word(self):
        self.example.word = ''
        self.assertEqual(self.example.goo_link(), '')

    def test_goo_link_exact_uses_a_different_search_mode(self):
        """m1u rather than m0u, with Japanese label text."""
        link = self.example.goo_link_exact()
        self.assertIn('/m1u/', link)
        self.assertIn('「閲覧」で一致する言葉を検索', link)

    def test_goo_link_exact_is_empty_without_a_word(self):
        self.example.word = ''
        self.assertEqual(self.example.goo_link_exact(), '')

    def test_get_definition_html_renders_markdown(self):
        self.example.definition = 'これは **重要** です'
        self.assertEqual(self.example.get_definition_html(),
                         '<p>これは <strong>重要</strong> です</p>')

    def test_get_definition2_html_renders_markdown(self):
        self.example.definition2 = '*別の意味*'
        self.assertEqual(self.example.get_definition2_html(),
                         '<p><em>別の意味</em></p>')

    def test_get_word_native_prefers_the_native_form(self):
        self.example.word_native = '閲覧す'
        self.assertEqual(self.example.get_word_native(), '閲覧す')

    def test_get_word_native_falls_back_to_word(self):
        self.assertEqual(self.example.get_word_native(), '閲覧')


class ExampleSplitFieldsTest(TestCase):
    """`word` and `yomi` may hold two variants separated by '・'."""

    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        self.example = Example.objects.create(
            word='閲覧・閲覧す', yomi='エツラン・エツランス', sentence='',
            is_joyo=False)

    def test_first_and_second_word(self):
        self.assertEqual(self.example.word1, '閲覧')
        self.assertEqual(self.example.word2, '閲覧す')

    def test_first_and_second_yomi(self):
        self.assertEqual(self.example.yomi1, 'エツラン')
        self.assertEqual(self.example.yomi2, 'エツランス')

    def test_second_is_empty_when_there_is_no_separator(self):
        self.example.word = '閲覧'
        self.assertEqual(self.example.word1, '閲覧')
        self.assertEqual(self.example.word2, '')

    def test_split_and_get_returns_empty_beyond_the_end(self):
        self.assertEqual(Example.split_and_get('a・b', 5), '')


class ExampleKankenDerivationTest(TestCase):
    """`Example.save` derives kanken from the kanji in `word`."""

    fixtures = ['baseline', '閲', '覧', '斌', '劉', '遥']

    def test_kanken_is_the_hardest_kanji_in_the_word(self):
        example = Example.objects.create(word='閲覧', yomi='エツラン',
                                         sentence='', is_joyo=False)
        self.assertEqual(example.kanken, Kanken.objects.get(kyu='３級'))

    def test_a_harder_kanji_raises_the_level(self):
        example = Example.objects.create(word='閲斌', yomi='エツヒン',
                                         sentence='', is_joyo=False)
        self.assertEqual(example.kanken.difficulty,
                         max(Kanji.qget('閲').kanken.difficulty,
                             Kanji.qget('斌').kanken.difficulty))

    def test_kanken_is_recomputed_on_every_save(self):
        example = Example.objects.create(word='閲覧', yomi='エツラン',
                                         sentence='', is_joyo=False)
        example.word = '閲斌'
        example.save()
        self.assertNotEqual(example.kanken, Kanken.objects.get(kyu='３級'))

    def test_duplicate_word_and_kind_is_rejected(self):
        Example.objects.create(word='閲覧', yomi='エツラン', sentence='',
                               is_joyo=False)
        with self.assertRaisesMessage(ValidationError, 'この言葉は既に登録されている。'):
            Example.objects.create(word='閲覧', yomi='エツラン', sentence='',
                                   is_joyo=False)

    def test_duplicate_kotowaza_is_rejected_with_its_own_message(self):
        Example.objects.create(word='閲覧', yomi='エツラン', sentence='文',
                               is_joyo=False, ex_kind=Example.KOTOWAZA)
        with self.assertRaisesMessage(ValidationError, 'この諺は既に登録されている。'):
            Example.objects.create(word='閲覧', yomi='エツラン', sentence='文',
                                   is_joyo=False, ex_kind=Example.KOTOWAZA)

    def test_duplicate_ruigi_is_rejected_with_its_own_message(self):
        Example.objects.create(word='閲覧', yomi='エツラン', sentence='文',
                               is_joyo=False, ex_kind=Example.RUIGI)
        with self.assertRaisesMessage(ValidationError,
                                      'この対義語・類義語は既に登録されている。'):
            Example.objects.create(word='閲覧', yomi='エツラン', sentence='文',
                                   is_joyo=False, ex_kind=Example.RUIGI)

    def test_editing_an_existing_row_is_not_a_duplicate(self):
        """validate_unique only guards inserts; a re-save must not trip it."""
        example = Example.objects.create(word='閲覧', yomi='エツラン',
                                         sentence='', is_joyo=False)
        example.sentence = '変更した'
        example.save()
        self.assertEqual(Example.objects.filter(word='閲覧').count(), 1)


class ReadingExampleListTest(TestCase):
    """`Reading.get_list_ex*` join example anchors for the kanji page."""

    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        self.reading = Reading.objects.get(kanji='閲', reading='エツ')
        self.example = Example.objects.create(
            word='閲覧', yomi='エツラン', sentence='資料を閲覧する', is_joyo=False)
        self.kanji = Kanji.objects.get(kanji='閲')

    def add_map(self, in_joyo_list):
        ExMap.objects.create(example=self.example, kanji=self.kanji,
                             reading=self.reading, is_ateji=False,
                             in_joyo_list=in_joyo_list, map_order=0)

    def test_empty_when_no_examples_are_mapped(self):
        self.assertEqual(self.reading.get_list_ex2(), '')

    def test_joyo_examples_are_listed(self):
        self.add_map(in_joyo_list=True)
        self.assertEqual(self.reading.get_list_ex2(), self.example.get_url())

    def test_non_joyo_examples_are_separated_by_a_slash(self):
        self.add_map(in_joyo_list=False)
        self.assertEqual(self.reading.get_list_ex2(),
                         ' / ' + self.example.get_url())

    def test_get_list_ex_anki_uses_goo_links(self):
        self.add_map(in_joyo_list=True)
        self.assertEqual(self.reading.get_list_ex_anki(),
                         self.example.goo_link())

    def test_get_list_ex_joins_with_an_ideographic_comma(self):
        second = Example.objects.create(word='閲する', yomi='ケミスル',
                                        sentence='', is_joyo=False)
        self.reading.example_set.add(self.example, second)
        self.assertIn('、', self.reading.get_list_ex())


class KotowazaTest(TestCase):
    fixtures = ['baseline']

    def setUp(self):
        self.kotowaza = Kotowaza.objects.create(
            kotowaza='犬も歩けば棒に当たる', yomi='いぬもあるけばぼうにあたる',
            definition='何かをしていれば **思わぬ幸運** に出会う')

    def test_str_includes_the_pk(self):
        self.assertEqual(str(self.kotowaza),
                         f'{self.kotowaza.pk} - 犬も歩けば棒に当たる')

    def test_get_absolute_url(self):
        self.assertEqual(self.kotowaza.get_absolute_url(),
                         f'/kotowaza/{self.kotowaza.pk}/')

    def test_get_definition_html_renders_markdown(self):
        self.assertEqual(
            self.kotowaza.get_definition_html(),
            '<p>何かをしていれば <strong>思わぬ幸運</strong> に出会う</p>')


class YojiTest(TestCase):
    fixtures = ['baseline', '閲', '覧', '斌', '劉']

    def setUp(self):
        self.yoji = Yoji.objects.create(
            yoji='閲覧斌劉', reading='エツランヒンリュウ',
            meaning='これは *説明* です')

    def test_kanken_is_derived_from_the_constituent_kanji(self):
        self.assertEqual(
            self.yoji.kanken.difficulty,
            max(Kanji.qget(k).kanken.difficulty for k in '閲覧斌劉'))

    def test_anki_cloze_is_a_four_digit_pattern(self):
        """Two '11' and two '22' in a random order, assigned once."""
        self.assertEqual(sorted(self.yoji.anki_cloze), ['1', '1', '2', '2'])
        self.assertIn(self.yoji.anki_cloze, ['1122', '2211'])

    def test_anki_cloze_is_stable_across_saves(self):
        """It drives existing Anki cards; regenerating it would reshuffle
        cards the user has already learned."""
        original = self.yoji.anki_cloze
        self.yoji.meaning = '変更'
        self.yoji.save()
        self.assertEqual(self.yoji.anki_cloze, original)

    def test_get_definition_html_renders_markdown_as_html5(self):
        self.assertEqual(self.yoji.get_definition_html(),
                         '<p>これは <em>説明</em> です</p>')

    def test_reading_as_list_splits_before_okurigana(self):
        self.yoji.reading = 'あお（い）'
        self.assertEqual(self.yoji.reading_as_list(), ['あお', '（い）'])

    def test_reading_as_list_without_okurigana_is_a_single_element(self):
        self.assertEqual(self.yoji.reading_as_list(), ['エツランヒンリュウ'])


class TestResultTest(TestCase):
    fixtures = ['baseline']

    def setUp(self):
        self.source = TestSource.objects.create(
            series='過去問', kyu='２級', year='2025')
        self.kanken = Kanken.objects.get(kyu='２級')

    def make_result(self, **items):
        return TestResult.objects.create(
            kanken=self.kanken, date=dt.date(2025, 6, 1), source=self.source,
            test_number=3, name='OGU', **items)

    def test_score_is_the_sum_of_the_ten_items(self):
        result = self.make_result(item_01=10, item_02=20, item_03=5)
        self.assertEqual(result.score, 35)

    def test_score_is_recomputed_on_save_not_accumulated(self):
        result = self.make_result(item_01=10)
        result.save()
        result.save()
        self.assertEqual(result.score, 10)

    def test_score_of_an_empty_result_is_zero(self):
        self.assertEqual(self.make_result().score, 0)

    def test_str_format(self):
        result = self.make_result()
        self.assertEqual(str(result), 'OGU ２級 3 - 2025-06-01')

    def test_source_str_without_a_section(self):
        self.assertEqual(str(self.source), '過去問 - ２級 - 2025')

    def test_source_str_with_a_section(self):
        self.source.section = '第一回'
        self.assertEqual(str(self.source), '過去問 - ２級 - 2025 (第一回)')


class BunruiTest(TestCase):
    def test_str(self):
        self.assertEqual(str(Bunrui.objects.create(bunrui='人物')), '人物')


class HtmlEmittingModelMethodsTest(TestCase):
    """Every model method that returns markup returns it *marked safe* and
    with its inputs escaped.

    These were built by string concatenation and returned plain `str`, which
    worked only for as long as every consumer was Vue's `v-html` or an Anki
    field. Server-rendering them needs the opposite of what concatenation
    gives: the tag marked safe, and everything interpolated into it escaped.
    A method that gets this wrong fails in one of two visible ways -- literal
    `&lt;a href=` on the page, or an injection -- and one test each catches
    both.
    """

    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        self.example = Example.objects.create(
            word='閲覧', yomi='エツラン', sentence='資料を閲覧する',
            definition='調べ見ること', is_joyo=False)

    def assertSafeHtml(self, value):
        self.assertIsInstance(value, SafeString,
                              f'{value!r} would be escaped by a template')

    def test_example_anchors_are_marked_safe(self):
        self.assertSafeHtml(self.example.get_url())
        self.assertSafeHtml(self.example.goo_link())
        self.assertSafeHtml(self.example.goo_link_exact())

    def test_definition_markdown_is_marked_safe(self):
        self.example.definition = 'これは **重要** です'
        self.example.definition2 = '*別の意味*'
        self.assertSafeHtml(self.example.get_definition_html())
        self.assertSafeHtml(self.example.get_definition2_html())

    def test_a_word_containing_markup_is_escaped_not_injected(self):
        self.example.word = '<script>alert(1)</script>'
        for link in [self.example.get_url(), self.example.goo_link(),
                     self.example.goo_link_exact()]:
            with self.subTest(link=link):
                self.assertNotIn('<script>', link)
                self.assertIn('&lt;script&gt;', link)

    def test_a_word_containing_a_quote_cannot_break_out_of_the_href(self):
        """The hrefs used to be unquoted, so escaping alone would not have
        been enough even once it was added."""
        self.example.word = 'x" onmouseover="alert(1)'
        link = self.example.goo_link()
        self.assertNotIn('onmouseover="', link)

    def test_joined_example_lists_stay_safe(self):
        """`'、'.join()` over SafeStrings returns a plain str, which the
        template then escapes -- the anchors would render as visible tags."""
        reading = Reading.objects.filter(kanji__kanji='閲').first()
        self.assertSafeHtml(reading.get_list_ex())
        self.assertSafeHtml(reading.get_list_ex2())
        self.assertSafeHtml(reading.get_list_ex_anki())
        self.assertSafeHtml(reading.get_html_format())

    def test_reading_markup_escapes_the_reading_but_keeps_the_okuri_span(self):
        reading = Reading.objects.filter(kanji__kanji='閲').first()
        reading.reading = '<b>けみ</b>（する）'
        rendered = reading.get_html_format()
        self.assertIn("<span class='okuri'>する</span>", rendered)
        self.assertNotIn('<b>', rendered)

    def test_kanji_basic_info_anchors_are_marked_safe(self):
        kanji = Kanji.objects.get(kanji='閲')
        values = dict(kanji.basic_info2())
        self.assertSafeHtml(values['外部辞典'])

    def test_kanji_external_ref_is_escaped_into_the_href(self):
        kanji = Kanji.objects.get(kanji='閲')
        kanji.kanjidetails.external_ref = 'https://x/" onclick="alert(1)'
        values = dict(kanji.basic_info2())
        self.assertNotIn('onclick="', values['外部辞典'])

    def test_a_kanji_with_no_variant_form_gets_no_variant_row(self):
        """`jitai['alt']` is `[label, [kanji, ...]]` -- a two-element list, so
        always truthy. Testing it rather than its second element appended a
        row labelled `None` with an empty value to every kanji without a
        variant, which is most of them."""
        kanji = Kanji.objects.get(kanji='閲')
        self.assertEqual(kanji.jitai['alt'][1], [])
        self.assertNotIn(None, dict(kanji.basic_info2()))

    def test_a_kanji_with_variant_forms_still_lists_them(self):
        kanji = Kanji.objects.get(kanji='閲')
        variant = Kanji.objects.get(kanji='覧')
        variant.kanjidetails.std_kanji = kanji
        variant.kanjidetails.save()
        # `jitai` is a cached_property, so re-read rather than invalidate.
        kanji = Kanji.objects.get(kanji='閲')

        label = kanji.jitai['alt'][0]
        values = dict(kanji.basic_info2())
        self.assertIn(label, values)
        self.assertIn('覧', values[label])
