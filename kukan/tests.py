import sys, os, datetime
import unittest
import django

from django.utils import timezone
from django.test import TestCase

sys.path.extend(['E:\\Django\\kukan', 'E:/Django/kukan'])
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kukansite.settings")
django.setup()

from kukan.templatetags.ja_tags import furigana_ruby, furigana_remove, furigana_bracket
from kukan.jautils import JpnText

from kukan.models import Kanji, Example, Reading, ExMap, Kanken, YomiType, YomiJoyo
from kukan.forms import ExampleForm
from django.db.models import Max
from django.test import Client
from django.contrib.auth.models import User


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


#
#
# class JpSentenceTests(TestCase):
#
#     def test_JpSentence_conversions(self):
#         sentence = JpSentence('部屋から町を[俯瞰|ふかん|f]する')
#         self.assertEqual(sentence.text_only(), '部屋から町を俯瞰する')
#         self.assertEqual(sentence, '部屋から町を[俯瞰|ふかん|f]する')
#         self.assertEqual(sentence.ruby(), '部屋から町を<ruby>俯瞰<rt>ふかん</rt></ruby>する')
#
#         sentence2 = JpSentence('遁辞を[弄|ろう|f]しても無駄だ。')
#         self.assertEqual(sentence2.text_only(), '遁辞を弄しても無駄だ。')
#
#
# class ExampleTest(TestCase):
#     fixtures = ['base', 'test_data']
#
#     def setUp(self):
#         self.ex = Example.objects.filter(word='遁辞')[0]
#         self.ex.sentence = '遁辞を[弄|ロウ|f]しても無駄だ。'
#         self.ex.save()
#
#     def test_testdb(self):
#         self.assertEqual(furigana_remove(self.ex.sentence), ' 遁辞を弄しても無駄だ。')
#         self.assertEqual(Example.objects.count(), 1)

class ModelTest(TestCase):
    fixtures = ['base', 'test_data']

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
    fixtures = ['baseline.json', 'test_data']

    def setUp(self):
        Reading.objects.create(kanji=Kanji.objects.get(kanji='閲'), reading='けみ（する）',
                               yomi_type=YomiType.objects.get(yomi_type='訓'),
                               joyo=YomiJoyo.objects.get(yomi_joyo='表外'), joyo_order=9999)
        Reading.objects.create(kanji=Kanji.objects.get(kanji='閲'), reading='エツ',
                               yomi_type=YomiType.objects.get(yomi_type='音'),
                               joyo=YomiJoyo.objects.get(yomi_joyo='常用'), joyo_order=4094)
        Reading.objects.create(kanji=Kanji.objects.get(kanji='覧'), reading='ラン',
                               yomi_type=YomiType.objects.get(yomi_type='音'),
                               joyo=YomiJoyo.objects.get(yomi_joyo='常用'), joyo_order=3543)
        Example.objects.create(word='閲する', yomi='ケミスル', sentence='膨大な資料を閲する', is_joyo=False)

    def SetHyogaiYomi(self):
        self.form_data['reading_selected'] = Reading.objects.get(kanji='閲', reading='けみ（する）').id
        form = ExampleForm(self.form_data, instance=self.example )
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
        self.assertEquals(Example.objects.get(word='閲する').kanken, Kanken.objects.get(kyu='準１級'))
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
        self.assertEqual(Example.objects.get(word='閲覧').kanken, Kanken.objects.get(kyu='３級'))


# class ExampleManipulation(TestCase):
#     def setUp(self):
#         User.objects.create_user('test_user', password='pwd')
#         self.client = Client()
#         response = self.client.post('/login/', {'username': 'test_user', 'password': 'pwd'})
#
#     def testCreate(self):
#         response = self.client.post('/example/add/', {'word': '閲する', 'yomi': 'けみする',
#                                                       'sentence': '膨大な資料を閲する', 'definition': '言葉の定義',
#                                                       'ex_kind': Example.HYOGAI, 'kotowaza': None, 'yomi_native': ''})
#         print(response)
#
#         self.assertEquals(Example.objects.get(word='閲する').kanken, Kanken.objects.get(kyu='３級'))

