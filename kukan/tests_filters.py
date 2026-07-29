"""Unit tests for `kukan.filters`.

Every list page in the site — kanji, 四字熟語, 諺, 例文, test results, and both
tempmon lists — funnels its query string through these classes. They build ORM
queries by string concatenation of field names and lookups, so nothing here is
checked at import time: a lookup that stops being valid fails at request time,
on one filter, on one page.

The tests drive `add_to_query` directly with the string a browser would send,
and assert on the rows that come back. That is deliberately one level below the
view: it keeps the assertions readable, and it pins the query semantics rather
than the JSON envelope (which `tests_ajax_list` covers).

Two areas are worth the attention they get here:

* `FGenericDateRange` parses naive strings and staples '+0900' on by hand. It is
  the only place in the codebase that hard-codes the offset, and it is a prime
  candidate to shift under a Django or Python upgrade.
* The '≠ ' prefix (U+2260, then a space) switches filter() to exclude(). It is
  produced by the Vue frontend and parsed by slicing `flt[0:2]`, so it is
  invisible to any grep for 'exclude'.
"""
import datetime as dt

from django.test import RequestFactory, TestCase

from kukan.filters import (
    FBushu,
    FGenericCheckbox,
    FGenericDateRange,
    FGenericMinMax,
    FGenericString,
    FGenericYesNo,
    FYomi,
    FYomiSimple,
)
from kukan.models import Classification, JisClass, Kanji, Kanken, KoukiBushu, Reading, YomiJoyo, YomiType


class FilterTestBase(TestCase):
    """A small, wholly synthetic kanji set with known field values.

    Built in code rather than loaded from `baseline` so that the numbers the
    assertions depend on are visible in this file.
    """

    @classmethod
    def setUpTestData(cls):
        cls.kanken_2 = Kanken.objects.create(kyu='2級', difficulty=10)
        cls.kanken_1 = Kanken.objects.create(kyu='1級', difficulty=12)

        cls.joyo = Classification.objects.create(classification='常用漢字')
        cls.jinmei = Classification.objects.create(classification='人名用漢字')

        cls.jis_1 = JisClass.objects.create(level='第1水準')
        cls.jis_2 = JisClass.objects.create(level='第2水準')

        cls.bushu_ki = KoukiBushu.objects.create(
            bushu='木', variations='', reading='き', number=75, kakusu=4)
        cls.bushu_mizu = KoukiBushu.objects.create(
            bushu='水', variations='', reading='みず', number=85, kakusu=4)
        cls.bushu_kuchi = KoukiBushu.objects.create(
            bushu='口', variations='', reading='くち', number=30, kakusu=3)

        # kanji, strokes, kanken, classification, jis, kouki_bushu
        rows = [
            ('校', 10, cls.kanken_2, cls.joyo, cls.jis_1, cls.bushu_ki),
            ('森', 12, cls.kanken_2, cls.joyo, cls.jis_1, cls.bushu_ki),
            ('汀', 5, cls.kanken_1, cls.jinmei, cls.jis_2, cls.bushu_mizu),
            ('叩', 5, cls.kanken_1, None, cls.jis_2, cls.bushu_kuchi),
        ]
        for kanji, strokes, kanken, classification, jis, bushu in rows:
            Kanji.objects.create(
                kanji=kanji, strokes=strokes, kanken=kanken,
                classification=classification, jis=jis, kouki_bushu=bushu)

        cls.on = YomiType.objects.create(yomi_type='音')
        cls.kun = YomiType.objects.create(yomi_type='訓')
        cls.joyo_yomi = YomiJoyo.objects.create(yomi_joyo='常用')
        cls.hyogai = YomiJoyo.objects.create(yomi_joyo='表外')

        # kanji, reading, reading_simple, type, joyo
        readings = [
            ('校', 'コウ', 'こう', cls.on, cls.joyo_yomi),
            ('森', 'シン', 'しん', cls.on, cls.joyo_yomi),
            ('森', 'もり', 'もり', cls.kun, cls.joyo_yomi),
            ('汀', 'テイ', 'てい', cls.on, cls.hyogai),
            ('汀', 'みぎわ', 'みぎわ', cls.kun, cls.hyogai),
        ]
        for kanji, reading, simple, yomi_type, joyo in readings:
            Reading.objects.create(
                kanji=Kanji.objects.get(kanji=kanji), reading=reading,
                reading_simple=simple, yomi_type=yomi_type, joyo=joyo,
                joyo_order=0)

    def assertFiltered(self, flt_obj, flt_string, expected, qry=None):
        """Assert the kanji surviving `flt_string`, as an unordered set."""
        qry = Kanji.objects.all() if qry is None else qry
        result = flt_obj.add_to_query(flt_string, qry)
        self.assertEqual({k.kanji for k in result}, set(expected))


class TestFFilterRequestPlumbing(FilterTestBase):
    """`FFilter.filter` reads the query string; absent means untouched."""

    def setUp(self):
        self.factory = RequestFactory()
        self.flt = FGenericMinMax('画数', 'strokes')

    def test_absent_parameter_leaves_query_untouched(self):
        request = self.factory.get('/kanji/list/')
        result = self.flt.filter(request, Kanji.objects.all())
        self.assertEqual(result.count(), 4)

    def test_present_parameter_is_applied(self):
        request = self.factory.get('/kanji/list/', {'画数': '5'})
        result = self.flt.filter(request, Kanji.objects.all())
        self.assertEqual({k.kanji for k in result}, {'汀', '叩'})

    def test_empty_parameter_raises_known_defect(self):
        """KNOWN DEFECT, pinned rather than endorsed.

        `filter` guards with `is not None`, so an empty value ('?画数=') is
        treated as a real filter and reaches the ORM, where a numeric field
        rejects ''. Live effect: `/kanji/list/?画数=&ajax=1` returns 500. The
        HTML page still renders 200, so the user sees a page whose table never
        populates rather than an error.

        The fix is to guard on falsiness instead, but that changes behaviour
        and belongs in its own change. This test exists so that whoever makes
        that fix sees this turn red and updates it deliberately.
        """
        request = self.factory.get('/kanji/list/', {'画数': ''})
        with self.assertRaises(ValueError):
            list(self.flt.filter(request, Kanji.objects.all()))


class TestFGenericMinMax(FilterTestBase):
    def setUp(self):
        self.flt = FGenericMinMax('画数', 'strokes')

    def test_exact_value(self):
        self.assertFiltered(self.flt, '10', ['校'])

    def test_closed_range_is_inclusive_at_both_ends(self):
        self.assertFiltered(self.flt, '5~10', ['汀', '叩', '校'])

    def test_open_ended_upper(self):
        self.assertFiltered(self.flt, '10~', ['校', '森'])

    def test_open_ended_lower(self):
        self.assertFiltered(self.flt, '~5', ['汀', '叩'])

    def test_negation_prefix_excludes(self):
        self.assertFiltered(self.flt, '≠ 5', ['校', '森'])

    def test_negation_prefix_with_range(self):
        self.assertFiltered(self.flt, '≠ 5~10', ['森'])

    def test_fully_open_range_matches_everything(self):
        self.assertFiltered(self.flt, '~', ['校', '森', '汀', '叩'])


class TestFGenericString(FilterTestBase):
    def test_contains_by_default(self):
        self.assertFiltered(FGenericString('漢字', 'kanji'), '校', ['校'])

    def test_custom_lookup_and_transform(self):
        """This is the KanjiListFilter configuration: the value is split into
        characters and matched with __in, so '校森' finds both."""
        flt = FGenericString('漢字', 'kanji', 'kanji__in', list)
        self.assertFiltered(flt, '校森', ['校', '森'])

    def test_traversed_field(self):
        flt = FGenericString('種別', 'classification__classification')
        self.assertFiltered(flt, '常用', ['校', '森'])

    def test_no_match(self):
        self.assertFiltered(FGenericString('漢字', 'kanji'), '龍', [])


class TestFGenericCheckbox(FilterTestBase):
    def setUp(self):
        self.flt = FGenericCheckbox(
            '種別', 'classification__classification', Kanji,
            none_label='常用・人名以外')

    def test_single_value(self):
        self.assertFiltered(self.flt, '常用漢字', ['校', '森'])

    def test_multiple_values_are_comma_space_separated(self):
        self.assertFiltered(self.flt, '常用漢字, 人名用漢字', ['校', '森', '汀'])

    def test_none_label_matches_null_rows(self):
        """The sentinel label is how the UI offers 'no value set'."""
        self.assertFiltered(self.flt, '常用・人名以外', ['叩'])

    def test_none_label_combines_with_real_values(self):
        self.assertFiltered(self.flt, '常用漢字, 常用・人名以外', ['校', '森', '叩'])

    def test_choices_list_values_with_none_at_the_end(self):
        extra = self.flt.get_choices()
        self.assertEqual(extra['comptype'], 'b-checkbox')
        labels = [e['label'] for e in extra['elements']]
        self.assertEqual(labels[-1], '常用・人名以外')
        self.assertIn('常用漢字', labels)

    def test_choices_can_put_none_first(self):
        flt = FGenericCheckbox('種別', 'classification__classification', Kanji,
                               none_label='未設定', none_position='start')
        labels = [e['label'] for e in flt.get_choices()['elements']]
        self.assertEqual(labels[0], '未設定')

    def test_two_column_layout_alternates_the_col_index(self):
        flt = FGenericCheckbox('漢検', 'kanken__kyu', Kanji, is_two_column=True)
        cols = [e['col'] for e in flt.get_choices()['elements']]
        self.assertEqual(cols, [0, 1])

    def test_no_null_rows_means_no_none_entry(self):
        """The ValueError branch: nothing to pop, so no sentinel is appended."""
        flt = FGenericCheckbox('漢検', 'kanken__kyu', Kanji, none_label='未設定')
        labels = [e['label'] for e in flt.get_choices()['elements']]
        self.assertNotIn('未設定', labels)


class TestFGenericYesNo(FilterTestBase):
    def test_yes_filters(self):
        flt = FGenericYesNo('種別', 'classification__classification', '常用漢字')
        self.assertFiltered(flt, 'Yes', ['校', '森'])

    def test_no_excludes(self):
        flt = FGenericYesNo('種別', 'classification__classification', '常用漢字')
        self.assertFiltered(flt, 'No', ['汀', '叩'])

    def test_inverse_swaps_the_two(self):
        """ExampleList uses inverse=True so that '例文有り' means sentence != ''."""
        flt = FGenericYesNo('種別', 'classification__classification', '常用漢字',
                            '有り', '無し', inverse=True)
        self.assertFiltered(flt, '有り', ['汀', '叩'])
        self.assertFiltered(flt, '無し', ['校', '森'])

    def test_unrecognised_value_falls_through_to_exclude(self):
        flt = FGenericYesNo('種別', 'classification__classification', '常用漢字')
        self.assertFiltered(flt, 'nonsense', ['汀', '叩'])

    def test_choices_are_a_radio_pair(self):
        flt = FGenericYesNo('日課', 'in_anki', True, '出る', '出ない')
        extra = flt.get_choices()
        self.assertEqual(extra['comptype'], 'b-radio')
        self.assertEqual([e['label'] for e in extra['elements']],
                         ['出る', '出ない'])


class TestFYomiSimple(FilterTestBase):
    """Used by YojiList against a plain reading column."""

    def setUp(self):
        self.flt = FYomiSimple('reading_simple')

    def assertReadings(self, flt_string, expected):
        result = self.flt.add_to_query(flt_string, Reading.objects.all())
        self.assertEqual({r.reading_simple for r in result}, set(expected))

    def test_starts_with(self):
        self.assertReadings('こ_位始', ['こう'])

    def test_contains(self):
        self.assertReadings('り_位含', ['もり'])

    def test_exact_when_position_is_neither(self):
        self.assertReadings('もり_位全', ['もり'])

    def test_katakana_input_is_folded_to_hiragana(self):
        """The UI can send either script; both must reach the hiragana column."""
        self.assertReadings('コウ_位始', ['こう'])


class TestFYomi(FilterTestBase):
    """The kanji-list reading filter: four fields packed into one string."""

    def setUp(self):
        self.flt = FYomi()

    def test_position_starts_with(self):
        self.assertFiltered(self.flt, 'こ_位始_読両_常全', ['校'])

    def test_position_contains(self):
        self.assertFiltered(self.flt, 'り_位含_読両_常全', ['森'])

    def test_position_exact(self):
        self.assertFiltered(self.flt, 'もり_位全_読両_常全', ['森'])

    def test_on_reading_only(self):
        self.assertFiltered(self.flt, 'し_位始_読音_常全', ['森'])

    def test_kun_reading_only(self):
        self.assertFiltered(self.flt, 'し_位始_読訓_常全', [])

    def test_joyo_only_excludes_hyogai(self):
        self.assertFiltered(self.flt, 'て_位始_読両_常用', [])

    def test_hyogai_only(self):
        self.assertFiltered(self.flt, 'て_位始_読両_常外', ['汀'])

    def test_katakana_input_is_folded_to_hiragana(self):
        self.assertFiltered(self.flt, 'コ_位始_読両_常全', ['校'])


class TestFBushu(FilterTestBase):
    def setUp(self):
        self.flt = FBushu()

    def test_filters_by_bushu_characters(self):
        """`flt` is used as an iterable of characters, so a bare string works."""
        self.assertFiltered(self.flt, '木', ['校', '森'])

    def test_multiple_bushu(self):
        self.assertFiltered(self.flt, '木水', ['校', '森', '汀'])

    def test_choices_group_by_stroke_count(self):
        extra = self.flt.get_choices()
        self.assertEqual(extra['kakusu'], {'min': 3, 'max': 4})
        by_strokes = {g['strokeNumber']: set(g['bushu'])
                      for g in extra['listBushu']}
        self.assertEqual(by_strokes[4], {'木', '水'})
        self.assertEqual(by_strokes[3], {'口'})


class TestFGenericDateRange(TestCase):
    """Date parsing, including the hard-coded +0900.

    `Example.created_time` is auto_now_add, so these tests use a model with a
    writable datetime instead: `PlaySession.start_time`. Times below are chosen
    around JST midnight to make the offset handling visible — if the '+0900'
    were dropped or the boundary arithmetic changed, the boundary cases fail
    while the mid-day ones would not.
    """

    @classmethod
    def setUpTestData(cls):
        from tempmon.models import PlaySession
        cls.model = PlaySession

        def session(iso):
            """Create a session starting at the given JST wall-clock time."""
            start = dt.datetime.fromisoformat(iso)
            PlaySession.objects.create(
                start_time=start, end_time=start + dt.timedelta(hours=1),
                start_temp=20.0, max_temp=21.0, data_points=b'',
                duration=dt.timedelta(hours=1))
            return start

        cls.jan_01_early = session('2024-01-01T00:30:00+09:00')
        cls.jan_01_late = session('2024-01-01T23:30:00+09:00')
        cls.jan_02_noon = session('2024-01-02T12:00:00+09:00')
        cls.jan_05_noon = session('2024-01-05T12:00:00+09:00')

    def setUp(self):
        self.flt = FGenericDateRange('Start time', 'start_time')

    def assertStarts(self, flt_string, expected):
        result = self.flt.add_to_query(flt_string, self.model.objects.all())
        self.assertEqual({s.start_time for s in result}, set(expected))

    def test_single_date_covers_the_whole_jst_day(self):
        """Both 00:30 and 23:30 JST belong to 2024-01-01, and nothing else does.

        This is the assertion that breaks if the +0900 stops being applied:
        under UTC the 23:30 row would fall into the next day.
        """
        self.assertStarts('2024-01-01', [self.jan_01_early, self.jan_01_late])

    def test_date_range_is_inclusive_of_the_end_day(self):
        """The end of a bare-date range is pushed out by one day so that the
        final day is included in full."""
        self.assertStarts('2024-01-01~2024-01-02',
                          [self.jan_01_early, self.jan_01_late,
                           self.jan_02_noon])

    def test_open_ended_upper(self):
        self.assertStarts('2024-01-02~', [self.jan_02_noon, self.jan_05_noon])

    def test_open_ended_lower(self):
        self.assertStarts('~2024-01-01', [self.jan_01_early, self.jan_01_late])

    def test_range_with_times_is_exclusive_at_the_end(self):
        """With an explicit time no day is added, so the bound is a strict <."""
        self.assertStarts('2024-01-01 00:00~2024-01-01 23:30',
                          [self.jan_01_early])

    def test_range_with_times_lower_bound_is_inclusive(self):
        self.assertStarts('2024-01-01 00:30~2024-01-01 12:00',
                          [self.jan_01_early])

    def test_negation_prefix_excludes(self):
        self.assertStarts('≠ 2024-01-01', [self.jan_02_noon, self.jan_05_noon])

    def test_negation_prefix_with_range(self):
        self.assertStarts('≠ 2024-01-01~2024-01-02', [self.jan_05_noon])

    def test_fully_open_range_matches_everything(self):
        self.assertStarts('~', [self.jan_01_early, self.jan_01_late,
                                self.jan_02_noon, self.jan_05_noon])


class TestFilterKind(FilterTestBase):
    """`kind` selects the rendering partial via
    `kukan.templatetags.util_tags.FILTER_TEMPLATES`. A typo here means a
    KeyError at render time, not a degraded widget, so pin the values."""

    def test_kind_selects_the_rendering_partial(self):
        from kukan.templatetags.util_tags import FILTER_TEMPLATES
        self.assertEqual(FBushu().kind, 'bushu')
        self.assertEqual(FYomi().kind, 'yomi')
        self.assertEqual(FYomiSimple('reading').kind, 'yomi-simple')
        self.assertEqual(FGenericDateRange('d', 'f').kind, 'daterange')
        self.assertEqual(FGenericString('s', 'f').kind, 'string')
        self.assertEqual(FGenericMinMax('m', 'f').kind, 'min-max')
        self.assertEqual(FGenericCheckbox('c', 'kanken__kyu', Kanji).kind,
                         'checkbox')
        self.assertEqual(
            FGenericYesNo('y', 'f', True).kind, 'checkbox')

        for flt in [FBushu(), FYomi(), FYomiSimple('reading'),
                    FGenericDateRange('d', 'f'), FGenericString('s', 'f'),
                    FGenericMinMax('m', 'f'),
                    FGenericCheckbox('c', 'kanken__kyu', Kanji),
                    FGenericYesNo('y', 'f', True)]:
            self.assertIn(flt.kind, FILTER_TEMPLATES)
