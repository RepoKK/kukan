import csv
import itertools as it
import json
import os
import re
import urllib.parse
from collections import Counter, namedtuple
from io import StringIO
from unittest import TestCase
from unittest.mock import mock_open, patch, MagicMock

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import QueryDict
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from kukan.apps import kukanConfig
from kukan.exporting import Exporter
from kukan.forms import ExampleForm, KotowazaForm
from kukan.jautils import JpnText, hir2kat
from kukan.jautils import kat2hir
from kukan.models import Kanji, Example, Reading, ExMap, Kanken, YomiJoyo, Kotowaza, Bushu
from kukan.templatetags.ja_tags import furigana_ruby, furigana_remove, furigana_bracket, furigana_html
from kukan.test_helpers import FixtureAppLevel, FixtureKukan, FixWebKukan, PatchRequestsGet
from kukan.test_helpers import FixtureKanji


class TestUtilsDjangoApps(TestCase):
    def test_apps(self):
        self.assertEqual(kukanConfig.name, 'kukan')


class FuriganaTest(TestCase):
    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def test_furigana_conversions(self):
        sentence = '[部屋|へや|f]から町を[俯瞰|ふかん|f]する'
        self.assertEqual('部屋から町を俯瞰する', furigana_remove(sentence))
        self.assertEqual('部屋(へや)から町を俯瞰(ふかん)する', furigana_bracket(sentence))
        self.assertEqual('<ruby>部屋<rt>へや</rt></ruby>から町を<ruby>俯瞰<rt>ふかん</rt></ruby>する',
                         furigana_ruby(sentence))

    def test_JpnText(self):

        # The source_furigana can be set to None, in which case the JpnText will be built from the expected 'bracket'
        for sentence, exclude, source_furigana, expected_results in [
            ('ご飯に差し支えない様に', None, None, {
                'bracket': 'ご[飯|はん|f]に[差し支|さしつか|f]えない[様|よう|f]に',
                'none': 'ご飯に差し支えない様に',
                'ruby': ('ご<ruby>飯<rt>はん</rt></ruby>に<ruby>差し支<rt>さしつか</rt></ruby>えない'
                         '<ruby>様<rt>よう</rt></ruby>に'),
                'simple': 'ご 飯[はん]に 差し支[さしつか]えない 様[よう]に',
            }),
            ('飛花落葉', None, None, {
                'bracket': '[飛花落葉|ひからくよう|f]',
                'none': '飛花落葉',
                'ruby': '<ruby>飛花落葉<rt>ひからくよう</rt></ruby>',
                'simple': '飛花落葉[ひからくよう]',
            }),
            ('平仮名ひらがなカタカナAlphabet', None, None, {
                'bracket': '[平仮名|ひらがな|f]ひらがなカタカナAlphabet',
                'none': '平仮名ひらがなカタカナAlphabet',
                'ruby': '<ruby>平仮名<rt>ひらがな</rt></ruby>ひらがなカタカナAlphabet',
                'simple': '平仮名[ひらがな]ひらがなカタカナAlphabet',
            }),
            ('ひ_カ_A', None, None, {
                'bracket': 'ひ_カ_A',
                'none': 'ひ_カ_A',
                'ruby': 'ひ_カ_A',
                'simple': 'ひ_カ_A',
            }),
            ('一竿の風月。', ['一竿'], '[一竿|いっかん|f]の[風月|ふうげつ|f]', {
                'bracket': '一竿の[風月|ふうげつ|f]',
                'none': '一竿の風月',
                'ruby': '一竿の<ruby>風月<rt>ふうげつ</rt></ruby>',
                'simple': '一竿の 風月[ふうげつ]',
            }),
        ]:
            jpn_text = JpnText.from_furigana_format(source_furigana or expected_results['bracket'])
            for kind, expected in expected_results.items():
                with self.subTest(sentence, kind=kind):
                    self.assertEqual(expected, jpn_text.furigana(kind, exclude))
                    if kind == 'bracket':
                        self.assertEqual(expected, jpn_text.furigana(exclude=exclude))

    def test_get_sub_token_errors(self):
        for origin, furigana in [
            ('漢字', ''), ('かな漢字', 'かかんじ'), ('かな', 'かなな'), ('かな', 'かなな'),
            ('かな漢字', 'かかなかんじ'), ('漢字かな', 'かんじな'), ('漢字かな', 'かんじかなな'),
            ('かな', '')
        ]:
            with self.subTest(origin=origin, furigana=furigana):
                with patch('kukan.jautils.JpnText.TextToken.__init__') as mock_text_token:
                    mock_text_token.return_value = None
                    with self.assertRaises(ValueError):
                        JpnText.TextToken.get_sub_token(origin, furigana)

    def test_from_text_unit(self):
        for pattern in ['かな', '漢字', 'かな-漢字', '漢字-かな', 'かな-漢字-かな']:
            surface = pattern.replace('-', '')
            reading = pattern.replace('漢字', 'かんじ').replace('-', '')
            tok_surface = pattern.split('-')
            tok_reading = [x for x in pattern.replace('かな', '').replace('漢字', 'かんじ').split('-')]

            with self.subTest(pattern=pattern):
                with patch('kukan.jautils.JpnText.LightTokenizer.tokenize') as mock_tokenize, \
                        patch('kukan.jautils.JpnText.TextToken.__init__') as mock_text_token, \
                        patch('kukan.jautils.JpnText._check_furigana'):
                    mock_tokenize.return_value = [MagicMock(surface=surface, reading=reading.translate(hir2kat))]
                    mock_text_token.return_value = None

                    JpnText.from_text(surface)

                    self.assertListEqual([(s, r) if r else (s,) for s, r in zip(tok_surface, tok_reading)],
                                         [x[0] for x in mock_text_token.call_args_list])

        with self.subTest(pattern='empty'):
            jpn_text = JpnText.from_text('')
            self.assertEqual('', jpn_text.text)

    def test_from_text_with_tokenize(self):
        for word_elements, furigana_elements in [
            (('漢字',), ('かんじ',)),
            (('お', '世話'), (None, 'せわ')),
            (('お', '差し支', 'え', 'なけれ', 'ば'), (None, 'さしつか', None, None, None)),
        ]:
            word = ''.join(word_elements)
            with self.subTest(word=word):
                with patch('kukan.jautils.JpnText.TextToken.__init__') as mock_text_token_init, \
                        patch('kukan.jautils.JpnText._check_furigana'):
                    mock_text_token_init.return_value = None
                    JpnText.from_text(word)
                    self.assertListEqual([(w, f) if f else (w,) for w, f in zip(word_elements, furigana_elements)],
                                         [x[0] for x in mock_text_token_init.call_args_list])

    def test_from_ruby(self):
        for ruby, expected in [
            ('<ruby>漢字<rt>かんじ</rt></ruby>', '[漢字|かんじ|f]'),
            ('<ruby>ご飯<rt>ごはん</rt></ruby>に<ruby>差し支え<rt>さしつかえ</rt></ruby>ない',
             'ご[飯|はん|f]に[差し支|さしつか|f]えない'),
            ('<ruby>破鏡<rt>はきょう</rt></ruby><ruby>再<rt>ふたた</rt></ruby>び<ruby>照' +
             '<rt>て</rt></ruby>らさず',
             '[破鏡|はきょう|f][再|ふたた|f]び[照|て|f]らさず'),
            ('しくじるは<ruby>稽古<rt>けいこ</rt></ruby>のため。',
             'しくじるは[稽古|けいこ|f]のため。')
        ]:
            with self.subTest(ruby=ruby):
                self.assertEqual(expected, JpnText.from_ruby(ruby).furigana())

    def test_from_ruby_invalid_input(self):
        ruby = '<ruby>漢字<rt>かんじ</ruby>'
        with self.assertRaises(TypeError):
            JpnText.from_ruby(ruby)

    def test_from_furigana_format(self):
        for test_text, expected_text, expected_hiragana in [
            ('[漢字|かんじ|f]', '漢字', 'かんじ'),
            ('ご[飯|はん|f]に[差し支|さしつか|f]えない', 'ご飯に差し支えない', 'ごはんにさしつかえない'),
            ('[破鏡|はきょう|f][再|ふたた|f]び[照|て|f]らさず', '破鏡再び照らさず', 'はきょうふたたびてらさず'),
            ('しくじるは[稽古|けいこ|f]のため。', 'しくじるは稽古のため。', 'しくじるはけいこのため。'),
            ('ヨリ', 'ヨリ', 'より'),
        ]:
            with self.subTest(test_text=test_text):
                jpn_text = JpnText.from_furigana_format(test_text, expected_text, expected_hiragana)
                self.assertEqual(expected_hiragana, jpn_text.hiragana())
                self.assertListEqual([], jpn_text.get_furigana_errors())

    def test_from_furigana_format_errors(self):
        for test_text, expected_dict, expected_errors in [
            ('[漢字|かんじ|f]', {'text': '漢字', 'expected_yomi': 'かんじ'}, []),
            ('[漢字|かんじ|f]', {'expected_yomi': 'かんじ'}, []),
            ('[漢字|かんじ|f]', {'text': '漢字'}, []),
            ('[漢字|かんじ|f]', {}, []),
            ('[漢字|かんじ|f]', {}, []),
            ('[漢字|かんじ|f]', {'text': '漢字', 'expected_yomi': 'かん'},
             ['推測振り仮名と元の読み方が合致しない']),
            ('[漢字|かんじ|f]', {'text': '感じ', 'expected_yomi': 'かんじ'},
             ['元の文章を復元出来ない: 「漢字」']),
            ('[漢字|かんじ|f]', {'text': '感じ', 'expected_yomi': 'かん'},
             ['元の文章を復元出来ない: 「漢字」', '推測振り仮名と元の読み方が合致しない']),
        ]:
            with self.subTest(test_text=test_text):
                jpn_text = JpnText.from_furigana_format(test_text, **expected_dict)
                self.assertListEqual(expected_errors, jpn_text.get_furigana_errors())

    def test_guess_furigana(self):
        sentence = '身体は芭蕉の如し、風に従って破れ易し。'
        yomi = 'しんたいはばしょうのごとし、かぜにしたがってやぶれやすし。'
        furigana = '[身体|しんたい|f]は[芭蕉|ばしょう|f]の[如|ごと|f]し、' + \
                   '[風|かぜ|f]に[従|したが|f]って[破|やぶ|f]れ[易|やす|f]し。'
        jpn_text = JpnText.from_text(sentence)
        self.assertEqual(sentence, jpn_text.furigana('none'))
        self.assertEqual(furigana, jpn_text.furigana())
        self.assertEqual(yomi, jpn_text.hiragana())

        sentence = 'よリ崩れル'
        yomi = 'ヨリクズレル'
        furigana = 'よリ[崩|くず|f]れル'
        jpn_text = JpnText.from_text(sentence)
        self.assertEqual(sentence, jpn_text.furigana('none'))
        self.assertEqual(furigana, jpn_text.furigana())
        self.assertEqual(yomi.translate(kat2hir), jpn_text.hiragana())

        for text, expected_yomi, expected_furigana, expected_errors in [
            ('漢字', 'かんじ', '[漢字|かんじ|f]', []),
        ]:
            with self.subTest(test_text=text):
                jpn_text = JpnText.from_text(text, expected_yomi)
                self.assertListEqual(expected_errors, jpn_text.get_furigana_errors())
                self.assertEqual(expected_furigana, jpn_text.furigana())

    def test_guess_furigana_error_yomi(self):
        for sentence, expected_yomi, expected_errors in [
            ('身体', 'からだ', ['推測振り仮名と元の読み方が合致しない'])
        ]:
            with self.subTest(sentence=sentence, expected_yomi=expected_yomi):
                jpn_text = JpnText.from_text(sentence, expected_yomi=expected_yomi)
                self.assertListEqual(expected_errors, jpn_text.get_furigana_errors())

    def test_guess_furigana_error_kanji(self):
        with patch('kukan.jautils.JpnText.LightTokenizer.tokenize') as mock_tokenize:
            mock_tokenize.return_value = [MagicMock(surface='身体', reading='カラダ')]
            jpn_text = JpnText.from_text('体', expected_yomi='からだ')

            self.assertListEqual(['元の文章を復元出来ない: 「身体」'], jpn_text.get_furigana_errors())

    def test_views_get_furigana(self):

        guess_error_msg = '推測振り仮名と元の読み方が合致しない'
        for param_dict, expected_response, expected_warnings in [
            ({'word': '漢字', 'yomi': 'かんじ'}, '[漢字|かんじ|f]', []),
            ({'word': '漢字'}, '[漢字|かんじ|f]', []),
            ({'word': '漢字', 'yomi': ''}, '[漢字|かんじ|f]', []),
            ({'word': '漢字', 'yomi': 'かん'}, '[漢字|かんじ|f]', [guess_error_msg]),
            ({'word': '', 'yomi': 'かんじ'}, '[||f]', [guess_error_msg]),
            ({'yomi': 'かん'}, '[||f]', [guess_error_msg]),
            ({}, '[||f]', []),
        ]:
            with self.subTest(**param_dict):
                response = self.client.get('/ajax/get_furigana/', data={**param_dict})
                self.assertEqual(expected_response, response.json()['furigana'])
                self.assertListEqual(expected_warnings, response.json()['furigana_notifications']['items'])
                self.assertEqual('is-warning', response.json()['furigana_notifications']['type'])

    def test_tag_furigana_html(self):
        for args, expected_result in [
            (['漢字', ''], '漢字'),
            (['', ''], ''),
            (['漢字', '[漢字|かんじ|f]'], '<ruby>漢字<rt>かんじ</rt></ruby>'),
            (['漢字', '[漢漢字|かんじ|f]'], '元の文章を復元出来ない: 「漢漢字」'),
        ]:
            with self.subTest(args):
                self.assertEqual(expected_result, furigana_html(*args))


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

    @staticmethod
    def get_reading_selected(list_readings):
        """
        Create reading_selected field, which
        :param list_readings: list of tuples (kanji, yomi in katakana)
        :return: comma-separated list of readings id
        """
        return ','.join([str(Reading.objects.get(kanji=k, reading=y).id) for k, y in list_readings])

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
                          'reading_selected': self.get_reading_selected([('閲', 'エツ'), ('覧', 'ラン')])}
        form = ExampleForm(self.form_data, instance=None)
        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual(Kanken.objects.get(kyu='３級'), Example.objects.get(word='閲覧').kanken)

        # Test for issue 22
        self.form_data = {'word': '遥遥', 'yomi': 'ハルバル', 'sentence': '遥遥',
                          'definition': '言葉の定義', 'ex_kind': Example.KAKI, 'yomi_native': '',
                          'reading_selected': self.get_reading_selected([('遥', 'はる（か）')] * 2)}

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

    def test_get_yomi_exmap_no_reading(self):
        """
        Test for issue #42: exception in case an Example has link to kanji, but not to the actual reading
        These examples come from automatic import of website tests, and didn't have reading attached.
        """
        ex = Example.objects.create(word='劉遥', yomi='リュウヨウ', sentence='劉遥を含む文', is_joyo=False)
        ExMap.objects.create(example=ex, kanji=Kanji.qget('劉'), is_ateji=False, in_joyo_list=False, map_order=1)

        response = self.call_get_yomi('劉遥', '劉遥')

        self.assertEqual(2, len(response.json()['reading_data']))
        self.assertListEqual([None, None], response.json()['reading_selected'])

    def test_get_yomi_okurigana(self):
        """
        Test for issue #44
        """
        response = self.client.get('/ajax/get_yomi/', data={'word': '閲する覧'})
        self.assertEqual(200, response.status_code)
        self.assertListEqual([None, None], response.json()['reading_selected'])

        response = self.client.get('/ajax/get_yomi/',
                                   data={'word': '閲する覧', 'reading_selected': '7463, 6422'})
        self.assertEqual(200, response.status_code)
        self.assertListEqual([7463, 6422], response.json()['reading_selected'])

    def test_get_yomi_missing_args(self):
        expected = {'reading_selected': [], 'reading_data': []}
        for data in [
            {'word': '', 'ex_id': 2, 'reading_selected': [7463, 6422]},
            {'word': '', 'ex_id': 2},
            {},
            {'reading_selected': [7463, 6422]},
            {'ex_id': 2, 'reading_selected': [7463, 6422]},
        ]:
            with self.subTest(data):
                response = self.client.get('/ajax/get_yomi/', data=data)
                self.assertEqual(200, response.status_code)
                self.assertEqual(expected, response.json())

    def test_set_yomi(self):
        for data, expected in [
            ({'word': '閲覧', 'yomi': 'えつらん'}, {'candidate': [7463, 6422]}),
            ({'word': '閲覧', 'yomi': 'エツラン'}, {'candidate': [7463, 6422]}),
            ({'word': '閲覧', 'word_native': '閲覧する', 'yomi': 'えつらん'}, {'candidate': [7463, 6422]}),
            ({'word': '閲覧閲覧', 'yomi': 'エツランエツラン'}, {'candidate': [7463, 6422, 7463, 6422]}),
            ({'word': '閲する', 'yomi': 'けみする'}, {'candidate': [7464]}),
            ({'word': '', 'yomi': ''}, {'candidate': []}),
            ({'word': ''}, {'candidate': []}),
            ({'word': '閲覧'}, {'candidate': []}),
            ({'yomi': ''}, {'candidate': []}),
            ({'yomi': 'エツラン'}, {'candidate': []}),
            ({}, {'candidate': []}),
        ]:
            with self.subTest(data):
                response = self.client.get('/ajax/set_yomi/', data=data)
                self.assertEqual(200, response.status_code)
                self.assertEqual(expected, response.json())

    def test_duplicate_kanji(self):
        expected_error = '漢字「閲」は単語「閲覧」以外では使えない。(\'x\'で無視可)'

        test_word = {'word': '閲覧', 'yomi': 'えつらん', 'sentence': '閲を閲覧する',
                     'definition': '言葉の定義', 'ex_kind': Example.KAKI, 'yomi_native': '',
                     'reading_selected': self.get_reading_selected([('閲', 'エツ'), ('覧', 'ラン')])}

        # To test the case the word is overridden by word_native.
        test_word_native = {**test_word, 'word': '劉遥', 'word_native': '閲覧'}

        for sub_test in ['test_word', 'test_word_native']:
            form_data = locals()[sub_test]
            with self.subTest(sub_test):
                response = self.client.post(reverse('kukan:example_add'), form_data)
                self.assertFormError(response, 'form', 'sentence', expected_error)
                self.assertEqual({'sentence': [expected_error]}, response.context['form'].errors)

                # Check that the duplicate error can be skipped by prefixing the sentence with x
                form = ExampleForm(data={**form_data, 'sentence': 'x閲を閲覧する'}, instance=None)
                self.assertTrue(form.is_valid())
                form.save()

                # Check the correct sentence (stripped from the x prefix) is in the database
                ex = Example.objects.last()
                self.assertEqual('閲を閲覧する', ex.sentence)

                # Test that updating without putting again the prefix fails
                form = ExampleForm(data={**form_data, 'sentence': '閲を閲覧'}, instance=ex)
                self.assertEqual({'sentence': [expected_error]}, form.errors)

                # But works with the prefix
                form = ExampleForm(data={**form_data, 'sentence': 'x閲を閲覧'}, instance=ex)
                form.save()
                ex.refresh_from_db()
                self.assertTrue(form.is_valid())
                self.assertEqual('閲を閲覧', ex.sentence)

                ex.delete()

    def test_no_sentence(self):
        form_data = {'word': '閲覧', 'yomi': 'えつらん', 'sentence': '',
                     'definition': '', 'ex_kind': Example.KAKI, 'yomi_native': '',
                     'reading_selected': self.get_reading_selected([('閲', 'エツ'), ('覧', 'ラン')])}
        form = ExampleForm(data=form_data, instance=None)
        self.assertTrue(form.is_valid())


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


class KotowazaFormTest(TestCase):
    fixtures = ['baseline', '閲', '覧', '斌', '劉', '遥']

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

        self.kotowaza = Kotowaza.objects.create(kotowaza='一')
        Example.objects.create(word='閲覧', yomi='エツラン', kotowaza=self.kotowaza, is_joyo=False, ex_kind=Example.KOTOWAZA)

    def test_form(self):
        form_data = {'kotowaza': '閲覧の風月', 'yomi': 'えつらんのふうげつ',
                     'furigana': '[閲覧|えつらん|f]の[風月|ふうげつ|f]',
                     'definition': '説明'}
        form = KotowazaForm(form_data, instance=self.kotowaza)
        self.assertTrue(form.is_valid())
        form.save()
        self.assertTrue(Kotowaza.objects.filter(**form_data).exists())

    def test_form_error(self):
        form_data = {'kotowaza': '閲覧の風', 'yomi': 'つらんのふうげつ',
                     'furigana': '[閲覧|えつらん|f]の[風月|ふうげつ|f]',
                     'definition': '説明'}

        response = self.client.post(reverse('kukan:kotowaza_update', args=[self.kotowaza.pk]),
                                    form_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'furigana',
                             ['元の文章を復元出来ない: 「閲覧の風月」',
                              '推測振り仮名と元の読み方が合致しない'])


class TestExport(TestCase):
    kanji_per_kyu = '一万丁不久並丈乏且串茅丐'
    fixtures = ['baseline', '汀', '渚', '渚', '覧'] + list(kanji_per_kyu)

    output_templt_kaki_hyogai = '{pk}\t"<span class=tag_hyogai>表外</span>' \
                                + '{kind}:<span class=""font-color01"">{yomi}</span>"\t{word}\t{kanken}\r\n'
    output_templt_kaki = output_templt_kaki_hyogai.replace('<span class=tag_hyogai>表外</span>', '')

    output_templt_yomi_hyogai = ('{pk}\t"<span class=tag_hyogai>表外</span>{kind}:<span class='
                                 + '""font-color01"">{word}</span>"\t{yomi}\t<p>{definition}</p>\r\n')
    output_templt_yomi = output_templt_yomi_hyogai.replace('<span class=tag_hyogai>表外</span>', '')

    output_templt_kotowaza = ('{pk}\t"{expected_text}"'
                              '\t{word}\t<p>{kotowaza_definition}</p>\t{kotowaza_yomi}\r\n')

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
                          if (Kanji.qget(kj).kanken >= Kanken.qget('準１級')
                              or
                              Reading.objects.get(kanji=kj, reading_simple=r).joyo == YomiJoyo.qget('表外'))]
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
            if ex_kind[0] != Example.JUKUICHI:
                res.append(self.create_example_with_reading(kanji_list * (idx + 1), ex_kind[0]))
        return res

    def assert_export_file(self, exporter, number_line, qry, output_template, **kwargs):
        with patch('builtins.open', mock_open()) as m:
            exporter.export()
            try:
                self.assertEqual(number_line + 3, len(m.mock_calls))
                for idx, ex in enumerate(qry):
                    name, m_args, m_kwargs = m.mock_calls[idx + 2]
                    file_write = m_args[0]
                    if ex.ex_kind == Example.KOTOWAZA:
                        kotowaza_args = {'kotowaza_yomi': ex.kotowaza.yomi,
                                         'kotowaza_definition': ex.kotowaza.definition}
                    else:
                        kotowaza_args = {}
                    self.assertEqual(output_template.format(pk=ex.pk, kind=ex.ex_kind, yomi=ex.yomi, word=ex.word,
                                                            kanken=ex.kanken, definition=ex.definition,
                                                            **kotowaza_args,
                                                            **kwargs),
                                     file_write)
            except AssertionError:
                print('\nList of calls of mock: \n' + str(m.mock_calls))
                raise

    def test_assert_export_file_function(self):
        """
        Test that above assert_export_file helper does return a proper Assertion with list of calls output
        (mostly for test coverage...)
        """
        with patch('builtins.print'), self.assertRaises(AssertionError):
            self.assert_export_file(Exporter('anki_kaki', 'Fred'), 3,
                                    Example.objects.filter(ex_kind__in=[Example.KAKI, Example.RUIGI, Example.TAIGI]),
                                    self.output_templt_kaki_hyogai)

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

    def test_export_kotowaza(self):
        Example.objects.all().delete()
        Kotowaza.objects.all().delete()

        kotowaza = Kotowaza.objects.create(kotowaza='一竿の風月', yomi='いっかんのふうげつ',
                                           furigana='[一竿|いっかん|f]の[風月|ふうげつ|f]', definition='説明')
        Example.objects.create(word='一竿', yomi='イッカン', kotowaza=kotowaza, is_joyo=False, ex_kind=Example.KOTOWAZA)

        self.create_example_all_kinds([('覧', 'みる')])

        self.assert_export_file(Exporter('anki_kotowaza', 'Fred'), 1,
                                Example.objects.filter(ex_kind=Example.KOTOWAZA).exclude(kotowaza__isnull=True),
                                self.output_templt_kotowaza,
                                expected_text='<span class=""font-color01"">イッカン</span>の 風月[ふうげつ]')

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
                          for ex_kind in [x[0] for x in Example.EX_KIND_CHOICES
                                          if not x[0] in [Example.HYOGAI, Example.JUKUICHI]]],
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


class TestIndexView(TestCase):
    fixtures = ['baseline', '閲', '覧', '斌', '劉', '遥']

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})

    def assertCheckResponse(self, view_name, data, expected_query_string):
        response = self.client.post(reverse('kukan:index'), follow=True, data=data)
        base_url = reverse('kukan:{}'.format(view_name))
        if expected_query_string is None:
            self.assertRedirects(response, base_url)
        else:
            expected_query_string = urllib.parse.quote(expected_query_string, safe='=&')
            self.assertRedirects(response, '{}?{}'.format(base_url, expected_query_string))
        # Check the filters are correct
        request_keys = QueryDict(urllib.parse.unquote(response.request['QUERY_STRING'])).keys()
        view_filters = [x.label for x in response.context_data['view'].filters]
        self.assertTrue(all(k in view_filters for k in request_keys))

    def test_search_yoji(self):
        for search_text, expected_query_string in [
            ('', None), ('せいせい', '読み=せいせい_位含'), ('生生流転', '漢字=生生流転')
        ]:
            with self.subTest(search_text=search_text):
                if expected_query_string is not None:
                    expected_query_string = '{}&日課=日課に出る'.format(expected_query_string)
                self.assertCheckResponse('yoji_list',
                                         {'search': search_text, 'yoji': '四字熟語'},
                                         expected_query_string)

    def test_search_kotowaza(self):
        for search_text, expected_query_string in [
            ('', None), ('閲覧', '諺=閲覧'), ('覧閲', '諺=覧閲')
        ]:
            with self.subTest(search_text=search_text):
                self.assertCheckResponse('kotowaza_list',
                                         {'search': search_text, 'kotowaza': '諺'},
                                         expected_query_string)

    def test_search_example(self):
        for search_text, expected_query_string in [
            ('', None), ('せ', '単語=せ'), ('生生流転', '単語=生生流転')
        ]:
            with self.subTest(search_text=search_text):
                self.assertCheckResponse('example_list',
                                         {'search': search_text, 'example': '諺'},
                                         expected_query_string)

    def test_search_kanji(self):
        for search_text, expected_query_string in [
            ('', None), ('生生流転', '漢字=生生流転'), ('こだわるル', '読み=こだわるる_位始_読両_常全')
        ]:
            with self.subTest(search_text=search_text):
                self.assertCheckResponse('kanji_list',
                                         {'search': search_text, 'kanji': '漢字'},
                                         expected_query_string)

        for search_text in [
            '閲', '閲する', '閲すル'
        ]:
            with self.subTest(search_text=search_text):
                response = self.client.post(reverse('kukan:index'), follow=True, data={'search': search_text})
                base_url = reverse('kukan:{}'.format('kanji_detail'), args='閲')
                self.assertRedirects(response, base_url)


class TestBushu(TestCase):
    fixtures = ['baseline']

    def test_bushu_str(self):
        Bushu.objects.create(bushu='⺌', reading='しょう')
        self.assertEqual('⺌　(しょう)', str(Bushu.objects.first()))

    def test_kouki_bushu_str(self):
        Bushu.objects.create(bushu='匕', reading='ヒ さじ さじのひ')
        self.assertEqual('匕　(ヒ さじ さじのひ)', str(Bushu.objects.first()))


class TestExampleCreateExmap(TestCase):
    fixtures = ['baseline', '閲', '覧', '斌', '劉', '遥']

    msg_assert_change = 'Existing Joyo reading cannot be modified'
    msg_assert_num_mis = 'Reading number mismatch'

    TestDef = namedtuple('TestDef', 'result sub_test word readings  args', defaults=(None,))

    @staticmethod
    def get_reading_id_from_reading(readings):
        """
        Return a list of Reading id from a list of reading (hardcoded in reading_id_map).
        :param readings: list of reading as string
                          'A<kanji>' would create the Ateji_<kanji> reading
        :return: list of Reading objects ids, of the same length as readings
        """
        reading_id_map = {'エツ': 7463, 'へ（る）': 7465, 'ラン': 6422, 'ヒン': 9575}
        res = []
        for reading in readings:
            if str(reading)[0] == 'A':
                res.append('Ateji_' + reading[1])
            else:
                res.append(str(reading_id_map[reading]))
        return res

    def check_database_after_create_exmap(self, example, word, readings, is_joyo=it.repeat(False)):
        """
        Ensure that the database entries for ExMap are matching the expected result
        :param example: the Example instance
        :param word: word containing Kanji and potentially kana / other (will be cleaned)
        :param readings: the readings corresponding to word, potentially 'A' for Ateji
        :param is_joyo: iterable of boolean, defining if the corresponding reading is a Joyo one.
        """
        cleaned_word = ''.join([x for x in word if Kanji.objects.filter(kanji=x).exists()])
        for pos, (kj, reading, joyo) in enumerate(zip(cleaned_word, readings, is_joyo)):
            if reading[0] == 'A':
                exmap = ExMap.objects.get(example=example, kanji=cleaned_word[pos], map_order=pos)
                self.assertTrue(exmap.is_ateji)
                self.assertIsNone(exmap.reading)
            else:
                exmap = ExMap.objects.get(
                    example=example, reading__reading=reading, kanji=cleaned_word[pos], map_order=pos)
            self.assertEqual(joyo, exmap.in_joyo_list)
        self.assertEqual(ExMap.objects.count(), len(readings))

    def check_success(self, example, word, reading, is_joyo=it.repeat(False)):
        example.create_exmap(self.get_reading_id_from_reading(reading))
        self.check_database_after_create_exmap(example, word, reading, is_joyo)

    def check_assert(self, example, _, reading, assertion_msg):
        with self.assertRaisesMessage(AssertionError, assertion_msg):
            example.create_exmap(self.get_reading_id_from_reading(reading))

    def run_tests(self, example, test):
        with self.subTest(f'{test.result} - {test.sub_test}'):
            args = test.args or []
            if not isinstance(args, list):
                args = [args]
            example.word = test.word
            example.word_native = ''
            example.save()
            getattr(self, f'check_{test.result}')(example, test.word, test.readings, *args)
            # Test with the native word as well
            example.word = '遥dummy'
            example.word_native = test.word
            example.save()
            getattr(self, f'check_{test.result}')(example, test.word, test.readings, *args)

    def test_create_exmap_joyo(self):
        # Test target: 閲覧, 閲is part of the Joyo table
        example = Example.objects.create(word='閲覧', is_joyo=True)
        ExMap.objects.create(example=example, kanji=Kanji.qget('閲'),
                             reading=Reading.objects.get(kanji='閲', reading='エツ'),
                             map_order=0, is_ateji=False, in_joyo_list=True)

        test_definitions = [
            ['success', 'Set the second reading',    '閲覧',   ('エツ', 'ラン'),          (True, False)],
            ['success', 'Set second as Ateji',       '閲覧',   ('エツ', 'A覧'),           (True, False)],
            ['assert',  'Change the Joyo reading',  '閲覧',   ('へ（る）', 'ラン'),      self.msg_assert_change],
            ['assert',  'Change the Joyo to Ateji', '閲覧',   ('A閲', 'ラン'),           self.msg_assert_change],
            ['assert',  'Change Joyo position',      '覧閲覧', ('ラン', 'エツ', 'ラン'), self.msg_assert_change],
            ['assert',  'Delete the Joyo',            '覧',     ('ラン',),                 self.msg_assert_change],
        ]

        for test_definition in test_definitions:
            self.run_tests(example, self.TestDef(*test_definition))

    def test_create_exmap_joyo_ateji(self):
        # Same as test_create_exmap_joyo, but the Joyo part is 覧 and is an Ateji
        Example.objects.create(word='閲', is_joyo=True)  # Dummy
        example = Example.objects.create(word='閲覧', is_joyo=True)
        ExMap.objects.create(example=example, kanji=Kanji.qget('覧'),
                             map_order=1, is_ateji=True, in_joyo_list=True)

        test_definitions = [
            ['success', 'Set the first reading',   '閲覧',   ('エツ', 'A覧'),          (False, True)],
            ['success', 'Set first Ateji',          '閲覧',   ('A閲', 'A覧'),           (False, True)],
            ['assert',  'Change the Joyo reading', '閲覧',   ('エツ', 'ラン'),         self.msg_assert_change],
            ['assert',  'Change Joyo position',    '覧閲覧', ('ラン', 'エツ', 'A覧'),  self.msg_assert_change],
            ['assert',  'Delete the Joyo',          '閲',     ('エツ',),                  self.msg_assert_change],
            ['assert',  'Too few readings',         '閲覧',   ('エツ',),                  self.msg_assert_num_mis],
            ['assert',  'Too many readings',        '閲覧',   ('エツ', 'ラン', 'ラン'), self.msg_assert_num_mis]
        ]

        for test_definition in test_definitions:
            self.run_tests(example, self.TestDef(*test_definition))

    def test_create_exmap_non_joyo(self):
        example = Example.objects.create(word='閲覧斌', is_joyo=False)

        test_definitions = [
            ['success',   'Simple',         '閲',         ('エツ',)],
            ['success',   'Multiple',       '閲覧斌',    ('エツ', 'ラン', 'ヒン')],
            ['success',   'Ateji',          '閲斌斌',     ('エツ', 'ヒン', 'A斌')],
            ['assert',    'Extra chars 1', '閲hあア斌', ('エツ', *['エツ']*3, 'ヒン'), self.msg_assert_num_mis],
            ['success',   'Extra chars 2', '閲hあア斌', ('エツ', 'ヒン')],
            ['success',    'Single again',  '閲',         ('へ（る）',)],
        ]

        for test_definition in test_definitions:
            self.run_tests(example, self.TestDef(*test_definition))

    def test_create_exmap_no_kanji(self):
        # Not really possible to run any test for no kanji case due to following
        with self.assertRaises(Kanken.DoesNotExist):
            Example.objects.create(word='a', is_joyo=False)
