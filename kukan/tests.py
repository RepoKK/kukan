import csv
import json
import os
import re
import urllib.parse
from collections import Counter
from io import StringIO
from unittest.mock import mock_open, patch

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.test import Client
from django.test import TestCase

from kukan.exporting import Exporter
from kukan.forms import ExampleForm
from kukan.jautils import JpnText
from kukan.models import Kanji, Example, Reading, ExMap, Kanken, YomiJoyo
from kukan.templatetags.ja_tags import furigana_ruby, furigana_remove, furigana_bracket
from kukan.test_helpers import FixtureAppLevel, FixtureKukan, FixWebKukan, PatchRequestsGet
from kukan.test_helpers import FixtureKanji
from kukan.jautils import kat2hir


class FuriganaTest(TestCase):
    def test_furigana_conversions(self):
        sentence = '[部屋|へや|f]から町を[俯瞰|ふかん|f]する'
        self.assertEqual('部屋から町を俯瞰する', furigana_remove(sentence))
        self.assertEqual('部屋(へや)から町を俯瞰(ふかん)する', furigana_bracket(sentence))
        self.assertEqual('<ruby>部屋<rt>へや</rt></ruby>から町を<ruby>俯瞰<rt>ふかん</rt></ruby>する',
                         furigana_ruby(sentence))

    def test_JpnText(self):
        sentence = 'ご飯に差し支えない様に'
        jpn_text = JpnText.from_simple_text(sentence)
        self.assertEqual('[ご飯|ごはん|f]に[差し支え|さしつかえ|f]ない[様|よう|f]に', jpn_text.furigana())
        self.assertEqual('ご飯に差し支えない様に', jpn_text.furigana('none'))
        self.assertEqual('<ruby>ご飯<rt>ごはん</rt></ruby>に<ruby>差し支え<rt>さしつかえ</rt></ruby>ない' +
                         '<ruby>様<rt>よう</rt></ruby>に',
                         jpn_text.furigana('ruby'))
        self.assertEqual('', JpnText.from_simple_text('').furigana())


class ModelTest(TestCase):
    fixtures = ['baseline', '閲']

    def testKyu(self):
        example = Example.objects.create(word='閲する', yomi='けみする', sentence='膨大な資料を閲する',
                                         is_joyo=False)
        self.assertEqual(example.kanken, Kanken.objects.get(kyu='３級'))
        example.save()
        self.assertEqual(example.kanken, Kanken.objects.get(kyu='３級'))

        # Assign a reading which is not Yojo
        reading = Reading.objects.get(kanji='閲', reading='けみ（する）')
        m = ExMap(example=example, reading=reading, kanji=Kanji.objects.get(kanji='閲'), is_ateji=False,
                  in_joyo_list=False, map_order=0)
        m.save()
        example.save()

        self.assertEqual(example.kanken, Kanken.objects.get(kyu='準１級'))


class ExampleFormTest(TestCase):
    fixtures = ['baseline', '閲', '覧', '斌', '劉', '遥']

    def setUp(self):
        Example.objects.create(word='閲する', yomi='ケミスル', sentence='膨大な資料を閲する', is_joyo=False)
        Example.objects.create(word='斌斌', yomi='ヒンピン', sentence='恩師の斌斌たる人柄が偲ばれる', is_joyo=False)
        Example.objects.create(word='劉覧', yomi='リュウラン', sentence='劉覧', is_joyo=False)

        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def SetHyogaiYomi(self):
        self.form_data['reading_selected'] = Reading.objects.get(kanji='閲', reading='けみ（する）').id
        form = ExampleForm(self.form_data, instance=self.example)
        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual(form.cleaned_data['yomi'], 'ケミスル')

    def SetJoyoYomi(self):
        self.form_data['reading_selected'] = Reading.objects.get(kanji='閲', reading='エツ').id
        form = ExampleForm(self.form_data, instance=self.example)
        self.assertTrue(form.is_valid())
        form.save()

    def testChangeKyuByReading(self):
        self.example = Example.objects.get(word='閲する')
        self.form_data = {'word': '閲する', 'yomi': 'けみする', 'sentence': '膨大な資料を閲する',
                          'definition': '言葉の定義', 'ex_kind': Example.HYOGAI, 'yomi_native': ''}
        self.assertEqual(Example.objects.get(word='閲する').kanken, Kanken.objects.get(kyu='３級'))
        self.SetHyogaiYomi()
        self.assertEqual(Example.objects.get(word='閲する').kanken, Kanken.objects.get(kyu='準１級'))
        self.SetJoyoYomi()
        self.assertEqual(Example.objects.get(word='閲する').kanken, Kanken.objects.get(kyu='３級'))

    def testCreateNewExample(self):
        self.form_data = {'word': '閲覧', 'yomi': 'えつらん', 'sentence': '膨大な資料を閲覧する',
                          'definition': '言葉の定義', 'ex_kind': Example.KAKI, 'yomi_native': '',
                          'reading_selected': ','.join([str(x) for x in
                                                        [Reading.objects.get(kanji='閲', reading='エツ').id,
                                                         Reading.objects.get(kanji='覧', reading='ラン').id]])}
        form = ExampleForm(self.form_data, instance=None)
        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual(Kanken.objects.get(kyu='３級'), Example.objects.get(word='閲覧').kanken)

        # Test for issue 22
        self.form_data = {'word': '遥遥', 'yomi': 'ハルバル', 'sentence': '遥遥',
                          'definition': '言葉の定義', 'ex_kind': Example.KAKI, 'yomi_native': '',
                          'reading_selected': ','.join([str(x) for x in
                                                        [Reading.objects.get(kanji='遥', reading='はる（か）').id,
                                                         Reading.objects.get(kanji='遥', reading='はる（か）').id]])}
        form = ExampleForm(self.form_data, instance=None)
        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual(Kanken.objects.get(kyu='準１級'), Example.objects.get(word='遥遥').kanken)

    def check_reading_selected(self, expected, word, example, currently_set):
        self.assertEqual(expected,
                         self.call_get_yomi(word, example, '', currently_set).json()['reading_selected'],
                         'Issue with word={}, currently_set={}'.format(word, currently_set))

    def call_get_yomi(self, word='', example='', word_native='', reading_selected=None):
        ex_id = Example.objects.get(word=example).id if example else ''
        return self.client.get('/ajax/get_yomi/', data={
            'word': word, 'ex_id': ex_id, 'word_native': word_native,
            'reading_selected': ','.join([str(x) if x is not None else '' for x in reading_selected or []])})

    def test_get_yomi_no_reading(self):
        """
        Test the views.get_yomi function in the case Example is not yet associated with Readings
        """
        # ****   Basic test
        response = self.call_get_yomi(word='劉覧', example='劉覧',
                                      word_native='', reading_selected='')
        # Check we get expected number of kanji
        self.assertEqual(2, len(response.json()['reading_data']))
        # Check we get back the correct readings, and nothing selected
        self.assertEqual(['Ateji_劉', 10319, 10320, 10321],
                         [x['key'] for x in response.json()['reading_data'][0]['readings']])
        self.assertEqual(['Ateji_覧', 6422, 6423],
                         [x['key'] for x in response.json()['reading_data'][1]['readings']])
        self.assertEqual([None, None], response.json()['reading_selected'])

        # ****   Test addition / removal of kanji with the reading set
        # Set the reading, then check the return is not changed
        self.check_reading_selected([10319, 6422], '劉覧', '劉覧', [10319, 6422])
        # Set the reading, then remove second kanji, check the first don't loose the reading
        self.check_reading_selected([10319], '劉', '劉覧', [10319, 6422])
        # Add second
        self.check_reading_selected([10319, None], '劉覧', '劉覧', [10319])
        # Add before / after
        self.check_reading_selected([None, 10319, None, None], '斌劉覧閲', '劉覧', [10319, None])

        # Select reading of second, and add before / after
        self.check_reading_selected([None, 10319, 6422, None], '斌劉覧閲', '劉覧', [None, 10319, 6422, None])

        # Invert first and second
        self.check_reading_selected([6422, 10319], '覧劉', '劉覧', [10319, 6422])

        # Add multiple identical kanjis
        self.check_reading_selected([10319, 6422, None], '劉覧劉', '劉覧', [6422, 10319])
        self.check_reading_selected([10319, None, 6422], '劉劉覧', '劉覧', [6422, 10319])

        # Set one to Ateji
        self.check_reading_selected(['Ateji_劉', 6422, 10319], '劉覧劉', '劉覧', ['Ateji_劉', 10319, 6422])
        # Move one from start to end
        self.check_reading_selected([6422, 'Ateji_劉', 10319], '覧劉劉', '劉覧', ['Ateji_劉', 6422, 10319])

        # Set all to Ateji
        self.check_reading_selected(['Ateji_劉', 'Ateji_覧', 'Ateji_劉'], '劉覧劉', '劉覧',
                                    ['Ateji_劉', 'Ateji_覧', 'Ateji_劉'])
        # Move one from start to end
        self.check_reading_selected(['Ateji_覧', 'Ateji_劉', 'Ateji_劉'], '覧劉劉', '劉覧',
                                    ['Ateji_劉', 'Ateji_覧', 'Ateji_劉'])

        # Test for issue 22
        self.check_reading_selected([9575, 9575], '斌斌', '斌斌', [9575, 9575])

    def create_example_with_reading(self, kanji_list):
        """
        Create a new example and the association with the readings
        :param kanji_list: list of tuple of Kanji / Reading (as string). Reading can take word 'Ateji'
        """
        word = ''.join([x[0] for x in kanji_list])
        reading_selected = ','.join(['Ateji_' + x[0] if x[1] == 'Ateji'
                                     else str(Reading.objects.get(kanji=x[0], reading=x[1]).id)
                                     for x in kanji_list])
        form_data = {'word': word, 'yomi': 'にせよみ', 'sentence': word,
                     'definition': '言葉の定義', 'ex_kind': Example.KAKI, 'yomi_native': '',
                     'reading_selected': reading_selected}
        form = ExampleForm(form_data, instance=None)
        self.assertTrue(form.is_valid())
        form.save()

    def test_get_yomi_with_reading(self):
        """
        Test the views.get_yomi function in the case Example is already associated with Readings
        """
        self.create_example_with_reading([('劉', 'リュウ'), ('閲', 'エツ')])
        self.check_reading_selected([10319, 7463], '劉閲', '劉閲', [None, None])
        self.check_reading_selected([10320, 7463], '劉閲', '劉閲', [10320, 7463])

        self.check_reading_selected([None, None], '閲閲', None, [None, None])
        self.create_example_with_reading([('閲', 'エツ'), ('閲', 'エツ')])
        self.check_reading_selected([7463, 7463], '閲閲', '閲閲', [None, None])

        self.create_example_with_reading([('覧', 'Ateji'), ('閲', 'エツ')])
        self.check_reading_selected(['Ateji_覧', 7463], '覧閲', '覧閲', [None, None])

        self.create_example_with_reading([('覧', 'Ateji'), ('閲', 'エツ'), ('覧', 'Ateji'), ('閲', 'Ateji')])
        self.check_reading_selected(['Ateji_覧', 7463, 'Ateji_覧', 'Ateji_閲'], '覧閲覧閲', '覧閲覧閲',
                                    [None, None, None, None])

    def test_get_yomi_joyo_list(self):
        """
        Test the views.get_yomi function in the case Example has Readings part of the Joyo list
        The important part is to not allow change of them
        """
        self.create_example_with_reading([('覧', 'ラン'), ('閲', 'Ateji')])
        ex = Example.objects.get(word='覧閲')
        ex.is_joyo = True
        ex.save()
        ex_map = ExMap.objects.get(example=ex, kanji='覧')
        ex_map.in_joyo_list = True
        ex_map.save()
        self.check_reading_selected([6422, 'Ateji_閲'], '覧閲', '覧閲', [None, None])
        self.assertTrue(self.call_get_yomi('覧閲', '覧閲', '', [None, None]).json()['reading_data'][0]['joyo'])

        # Check we can change the reading of non JoyoList normally
        self.check_reading_selected([6422, 7463], '覧閲', '覧閲', [6422, 7463])
        # Check we get an exception if trying to change the reading of a JoyoList (覧 below)
        with self.assertRaises(ValueError):
            self.check_reading_selected([6423, 7463], '覧閲', '覧閲', [6423, 7463])

        # Check the logic works with Ateji
        ex_map = ExMap.objects.get(example=ex, kanji='閲')
        ex_map.in_joyo_list = True
        ex_map.save()
        self.assertTrue(self.call_get_yomi('覧閲', '覧閲', '', [None, None]).json()['reading_data'][1]['joyo'])


class TestFixtureFunctions(TestCase):
    fixtures = ['baseline', '閲', '渚', '渚']

    def setUp(self):
        pass

    def check_kanji_count(self, kanji, expected_count):
        """
        Check whether a Kanji fixture has the expected number of items
        """
        fixture = FixtureKanji().dump('閲', to_file=False)
        values = [f['model'].split('.')[-1] for f in json.loads(fixture)]
        self.assertEqual(dict(Counter(values)), expected_count, 'Issue with ' + kanji)

    def test_related_kanji(self):
        self.check_kanji_count('閲', {'kanji': 1, 'koukibushu': 1, 'bushu': 1, 'reading': 3, 'kanjidetails': 1})
        self.check_kanji_count('渚', {'kanji': 1, 'koukibushu': 1, 'bushu': 1, 'reading': 3, 'kanjidetails': 1})
        self.check_kanji_count('渚', {'kanji': 1, 'koukibushu': 1, 'bushu': 1, 'reading': 3, 'kanjidetails': 1})

    def test_AppLevel(self):
        self.assertGreater(len(FixtureAppLevel('kukan', 'baseline').get_list_models()), 15)
        self.assertEqual(FixtureAppLevel('kukan', 'baseline', ['Bushu', 'Kanken']).get_list_models(),
                         ['kukan.Bushu', 'kukan.Kanken'])
        self.assertTrue('kukan.Bushu' not in FixtureAppLevel('kukan', 'baseline',
                                                             exclude_models=['Bushu']).get_list_models())

    def test_KukanAppFix(self):
        self.assertEqual(FixtureKukan('baseline').file_name, 'baseline.json')
        self.assertEqual(FixtureKukan('baseline.json').file_name, 'baseline.json')

        kukan_fixture = FixtureKukan('baseline')
        self.assertEqual(kukan_fixture.get_list_models(),
                         ['kukan.' + x for x in
                          ['Classification', 'JisClass', 'Kanken', 'YomiJoyo', 'YomiType']])
        self.assertEqual(kukan_fixture.output_dir, os.path.join(settings.BASE_DIR, 'kukan', 'fixtures'))


class TestExport(TestCase):
    kanji_per_kyu = '一万丁不久並丈乏且串茅丐'
    fixtures = ['baseline', '汀', '渚', '渚', '覧'] + list(kanji_per_kyu)

    output_templt_kaki_hyogai = '{pk}\t"<span class=tag_hyogai>表外</span>' \
                                + '{kind}:<span class=""font-color01"">{yomi}</span>"\t{word}\t{kanken}\r\n'
    output_templt_kaki = output_templt_kaki_hyogai.replace('<span class=tag_hyogai>表外</span>', '')

    output_templt_yomi_hyogai = ('{pk}\t"<span class=tag_hyogai>表外</span>{kind}:<span class='
                                 + '""font-color01"">{word}</span>"\t{yomi}\t<p>{definition}</p>\r\n')
    output_templt_yomi = output_templt_yomi_hyogai.replace('<span class=tag_hyogai>表外</span>', '')

    def setUp(self):
        Example.objects.create(word='汀渚', yomi='テイショ', sentence='汀渚', is_joyo=False)
        Example.objects.create(word='汀渚', yomi='テイショ', sentence='汀渚', is_joyo=False)

    def create_example_with_reading(self, kanji_list, ex_kind):
        """
        Create a new example and the association with the readings
        :param kanji_list: list of tuple of Kanji / Reading (as string). Reading can take word 'Ateji'
        :param ex_kind: type of the Example (Kaki, Yomi, etc). Set as one of the Example const (KAKI, ...)
        """
        if ex_kind == Example.HYOGAI:
            kanji_list = [(kj, r) for kj, r in kanji_list
                          if (Kanji[kj].kanken >= Kanken['準１級']
                              or
                              Reading.objects.get(kanji=kj, reading_simple=r).joyo == YomiJoyo['表外'])]
        if len(kanji_list):
            word = ''.join([x[0] for x in kanji_list])
            reading_selected = ','.join(['Ateji_' + x[0] if x[1] == 'Ateji'
                                         else str(Reading.objects.get(kanji=x[0],
                                                                      reading_simple=x[1].translate(kat2hir)).id)
                                         for x in kanji_list])
            form_data = {'word': word, 'yomi': 'にせよみ', 'sentence': '{}:{}'.format(ex_kind, word),
                         'definition': '言葉の定義', 'ex_kind': ex_kind, 'yomi_native': '',
                         'reading_selected': reading_selected}
            form = ExampleForm(form_data, instance=None)
            self.assertTrue(form.is_valid())
            form.save()
            return form.instance
        else:
            return None

    def create_example_all_kinds(self, kanji_list):
        res = []
        for idx, ex_kind in enumerate(Example.EX_KIND_CHOICES):
            res.append(self.create_example_with_reading(kanji_list * (idx + 1), ex_kind[0]))
        return res

    def assert_export_file(self, exporter, number_line, qry, output_template):
        with patch('builtins.open', mock_open()) as m:
            exporter.export()
            try:
                self.assertEqual(number_line + 3, len(m.mock_calls))
                for idx, ex in enumerate(qry):
                    name, args, kwargs = m.mock_calls[idx + 2]
                    file_write = args[0]
                    self.assertEqual(output_template.format(pk=ex.pk, kind=ex.ex_kind, yomi=ex.yomi, word=ex.word,
                                                            kanken=ex.kanken, definition=ex.definition),
                                     file_write)
            except AssertionError:
                print('\nList of calls of mock: \n' + str(m.mock_calls))
                raise

    def test_export_issue_9(self):
        with StringIO() as out:
            writer = csv.writer(out, delimiter='\t', quotechar='"')
            Exporter('anki_kaki', 'Fred').export_anki_kaki(writer)
            self.assertEqual('1\t"<span class=""font-color01"">テイショ</span>"\t汀渚[汀渚]\t準１級\r\n' +
                             '2\t"<span class=""font-color01"">テイショ</span>"\t汀渚[汀渚]\t準１級\r\n',
                             out.getvalue())

    def test_export_kaki(self):
        with patch('builtins.open', mock_open()) as m:
            Exporter('anki_kaki', 'Fred').export()
        handle = m()
        handle.write.assert_any_call(
            '1\t"<span class=""font-color01"">テイショ</span>"\t汀渚[汀渚]\t準１級\r\n')

    def test_export_hyogai(self):
        Example.objects.all().delete()
        ex = self.create_example_all_kinds([('覧', 'みる')])
        self.assertEqual(Kanken.objects.get(kyu='準１級'), ex[0].kanken)

        self.assert_export_file(Exporter('anki_kaki', 'Fred'), 3,
                                Example.objects.filter(ex_kind__in=[Example.KAKI, Example.RUIGI, Example.TAIGI]),
                                self.output_templt_kaki_hyogai)

        self.assert_export_file(Exporter('anki_yomi', 'Fred'), 5,
                                Example.objects.exclude(ex_kind=Example.KOTOWAZA),
                                self.output_templt_yomi_hyogai)

    def test_export_all(self):
        Example.objects.all().delete()
        for kj in self.kanji_per_kyu:
            reading = Reading.objects.filter(kanji=kj, joyo=YomiJoyo.objects.get(yomi_joyo='常用')).first()
            if reading is None:
                reading = Reading.objects.filter(kanji=kj).first()
            self.create_example_all_kinds([(kj, reading.reading_simple)])
        # Check that each Kyu / Kind has exactly one example (HYOGAI are special - cannot have low Kanken)
        self.assertEqual([{'kanken__kyu': kanken.kyu, 'ex_kind': ex_kind, 'kanken__count': 1}
                          for kanken in Kanken.objects.all()
                          for ex_kind in [x[0] for x in Example.EX_KIND_CHOICES if x[0] is not Example.HYOGAI]],
                         list(Example.objects.exclude(ex_kind=Example.HYOGAI).values('kanken__kyu', 'ex_kind')
                              .annotate(Count('kanken')).order_by('pk')))
        self.assertEqual([{'kanken__kyu': kanken.kyu, 'ex_kind': ex_kind, 'kanken__count': 1}
                          for kanken in Kanken.objects.all() if kanken >= Kanken.objects.get(kyu='準１級')
                          for ex_kind in [Example.HYOGAI]],
                         list(Example.objects.filter(ex_kind=Example.HYOGAI).values('kanken__kyu', 'ex_kind')
                              .annotate(Count('kanken')).order_by('pk')))

        for kind, account, template, number_line, criteria, in [
            ('anki_kaki', 'Fred', self.output_templt_kaki, 3 * 11,
             Q(ex_kind__in=[Example.KAKI, Example.RUIGI, Example.TAIGI])),
            ('anki_kaki', 'Ayumi', self.output_templt_kaki, 4 + 2 * 11,
             (Q(ex_kind__in=[Example.KAKI], kanken__gte=Kanken.objects.get(kyu='３級'))
              | Q(ex_kind__in=[Example.TAIGI, Example.RUIGI]))),
            ('anki_yomi', 'Fred', self.output_templt_yomi, 15,
             (Q(ex_kind__in=[Example.KAKI, Example.TAIGI, Example.RUIGI], kanken__gte=Kanken.objects.get(kyu='準１級'))
              | Q(ex_kind__in=[Example.YOMI, Example.HYOGAI]))),
        ]:
            with self.subTest(kind=kind, account=account):
                # Currently only go up to 準一級
                criteria = criteria & Q(kanken__lte=Kanken.objects.get(kyu='準１級'))
                self.assert_export_file(Exporter(kind, account), number_line,
                                        Example.objects.filter(criteria),
                                        template)


@PatchRequestsGet('kukan.onlinepedia')
class TestDefinitionFetching(TestCase):

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def get_kanjipedia_def(self, word):
        self.mock_get.return_value = FixWebKukan().load_page('Kanjipedia', 'def_' + word)
        link = self.mock_get.return_value.url.replace('https://www.kanjipedia.jp', '')
        return self.client.get('/ajax/get_goo/', data={'word': word, 'word_native': '', 'link': link})

    def get_kanjipedia_def_string(self, word):
        return self.get_kanjipedia_def(word).json()['definition']

    def test_definition_with_icon(self):
        # Test for issue #22
        self.assertNotEqual(-1, self.get_kanjipedia_def_string('枯渇').find('【書きかえ】'))
        self.assertNotEqual(-1, self.get_kanjipedia_def_string('左様').find('【表記】'))


class TestPatchRequestGetDecorator(TestCase):
    def test_decorated_class(self):
        @PatchRequestsGet('kukan.tests')
        class DecoratorTarget(TestCase):
            def test_A(self):
                self.assertIsNotNone(self.mock_get)
                mock_return_string = 'requests.get override'
                self.mock_get.return_value = mock_return_string
                self.assertEqual(mock_return_string, requests.get('some fake URL'))

            def other_function(self):
                self.assertIsNone(self.mock_get)

        instance = DecoratorTarget()
        self.assertIsNone(instance.mock_get)
        instance.test_A()
        self.assertIsNone(instance.mock_get)
        self.assertEqual('test_A', DecoratorTarget.test_A.__name__)
        instance.other_function()

    def test_multiple_decorator(self):
        @PatchRequestsGet('kukan.onlinepedia', 'mock1')
        @PatchRequestsGet('kukan.tests', 'mock0')
        class DecoratorTarget(TestCase):
            def test_A(self):
                self.assertIsNotNone(self.mock0)
                self.assertIsNotNone(self.mock1)
                self.assertIsNot(self.mock0, self.mock1)
                self.assertNotEqual(self.mock0, self.mock1)
                mock_return_string0 = 'requests.get override 0'
                mock_return_string1 = 'requests.get override 1'
                self.mock0.return_value = mock_return_string0
                self.mock1.return_value = mock_return_string1
                self.assertEqual(mock_return_string0, requests.get('some fake URL'))

        instance = DecoratorTarget()
        self.assertIsNone(instance.mock0)
        self.assertIsNone(instance.mock1)
        instance.test_A()


class TestDecoratorPatchRequestGetDecorator(TestCase):
    def test_decorated_class(self):
        @PatchRequestsGet('kukan.tests')
        class DecoratorTarget(TestCase):
            def test_A(self):
                self.assertIsNotNone(self.mock_get)
                mock_return_string = 'requests.get override'
                self.mock_get.return_value = mock_return_string
                self.assertEqual(mock_return_string, requests.get('some fake URL'))

            def other_function(self):
                self.assertIsNone(self.mock_get)

        instance = DecoratorTarget()
        self.assertIsNone(instance.mock_get)
        instance.test_A()
        self.assertIsNone(instance.mock_get)
        self.assertEqual('test_A', DecoratorTarget.test_A.__name__)
        instance.other_function()

    def test_multiple_decorator(self):
        @PatchRequestsGet('kukan.onlinepedia', 'mock1')
        @PatchRequestsGet('kukan.tests', 'mock0')
        class DecoratorTarget(TestCase):
            def test_A(self):
                self.assertIsNotNone(self.mock0)
                self.assertIsNotNone(self.mock1)
                self.assertIsNot(self.mock0, self.mock1)
                self.assertNotEqual(self.mock0, self.mock1)
                mock_return_string0 = 'requests.get override 0'
                mock_return_string1 = 'requests.get override 1'
                self.mock0.return_value = mock_return_string0
                self.mock1.return_value = mock_return_string1
                self.assertEqual(mock_return_string0, requests.get('some fake URL'))

        instance = DecoratorTarget()
        self.assertIsNone(instance.mock0)
        self.assertIsNone(instance.mock1)
        instance.test_A()


class TestFilters(TestCase):
    fixtures = ['baseline', '閲']

    def setUp(self):
        Example.objects.create(word='閲する', yomi='ケミスル', sentence='膨大な資料を閲する', is_joyo=False)

        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def test_special_character(self):
        """
        Test case for issue #12
        """
        for character_list in ['ABC', 'ABC DEF', "A', 'yomi'", r'",/?:@&=+$#()!`~^[]|_/\\*.']:
            with self.subTest(character_list=character_list):
                response = self.client.get('/example/list/', {'page': 1, 'sort_by': 'kanken',
                                                              '意味': character_list})
                meaning_lines = [line for line in response.context_data['filter_list'].split('\n') if '意味' in line]
                self.assertEqual(1, len(meaning_lines))
                line = meaning_lines[0]
                search_obj = re.search('value(.*)', line)
                self.assertIsNotNone(search_obj)
                self.assertEqual("'{}'".format(character_list), urllib.parse.unquote(search_obj[0][7:-2]))

        character_list = 'Test "#$%&\'()"'
        response = self.client.get('/example/list/', {'page': 1, 'sort_by': 'kanken',
                                                      '意味': character_list})
        meaning_lines = [line for line in response.context_data['filter_list'].split('\n') if '意味' in line]
        self.assertEqual(1, len(meaning_lines))
        line = meaning_lines[0]
        search_obj = re.search('value(.*)', line)
        self.assertIsNotNone(search_obj)
        self.assertEqual("'{}'".format('Test%20%22%23%24%25%26%27%28%29%22'), search_obj[0][7:-2])
