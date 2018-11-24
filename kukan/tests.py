import sys, os, datetime
import unittest
import django

from django.utils import timezone
from django.test import TestCase

sys.path.extend(['E:\\Django\\kukan', 'E:/Django/kukan'])
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kukansite.settings")
django.setup()

from kukan.templatetags.ja_tags import furigana_ruby, furigana_remove, furigana_bracket


class FuriganaTest(TestCase):
    def test_furigana_conversions(self):
        sentence = '[部屋|へや|f]から町を[俯瞰|ふかん|f]する'
        self.assertEqual('部屋から町を俯瞰する', furigana_remove(sentence))
        self.assertEqual('部屋(へや)から町を俯瞰(ふかん)する', furigana_bracket(sentence))
        self.assertEqual('<ruby>部屋<rt>へや</rt></ruby>から町を<ruby>俯瞰<rt>ふかん</rt></ruby>する',
                         furigana_ruby(sentence))

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
#         self.ex.sentence = '遁辞を[弄|ロウ|j]しても無駄だ。'
#         self.ex.save()
#
#     def test_testdb(self):
#         self.assertEquals(self.ex.sentence.text_only(), '遁辞を弄しても無駄だ。')
#         print(self.ex.ruby())
