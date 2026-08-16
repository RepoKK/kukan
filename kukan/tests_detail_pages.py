"""Tests for the three Wave B "detail" pages: kotowaza_detail.html,
example_detail.html and yoji_detail.html. kanji_detail.html is deliberately
excluded — its dynamic per-category tabs make it one of Wave E's "hard ones"
instead.

None of these three had any view-level test before this stage; smoke_urls
only walks no-argument URLs, and a detail page always takes a pk.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from kukan.models import Kotowaza, Yoji


class DetailPageTestCase(TestCase):
    def setUp(self):
        User.objects.create_user('alice', password='hunter2')
        self.client.login(username='alice', password='hunter2')

    def assert_no_vue_or_buefy(self, response):
        content = response.content.decode()
        self.assertNotIn('vue_app', content)
        self.assertNotIn('buefy', content.lower())
        self.assertNotIn('<b-icon', content)
        self.assertNotIn('<b-field', content)


class KotowazaDetailTest(DetailPageTestCase):
    def setUp(self):
        super().setUp()
        self.kotowaza = Kotowaza.objects.create(
            kotowaza='一竿の風月', yomi='いっかんのふうげつ', furigana='',
            definition='自然を楽しむこと')

    def test_renders(self):
        response = self.client.get(
            reverse('kukan:kotowaza_detail', args=[self.kotowaza.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '一竿の風月')

    def test_no_vue_or_buefy_remains(self):
        response = self.client.get(
            reverse('kukan:kotowaza_detail', args=[self.kotowaza.pk]))
        self.assert_no_vue_or_buefy(response)


class ExampleDetailTest(DetailPageTestCase):
    fixtures = ['baseline', '閲']

    def setUp(self):
        super().setUp()
        from kukan.models import Example
        self.example = Example.objects.create(
            word='閲する', yomi='けみする', sentence='書類を閲する',
            definition='調べ確かめる', ex_kind=Example.KAKI, is_joyo=False)

    def test_renders(self):
        response = self.client.get(
            reverse('kukan:example_detail', args=[self.example.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '閲する')

    def test_no_vue_or_buefy_remains(self):
        response = self.client.get(
            reverse('kukan:example_detail', args=[self.example.pk]))
        self.assert_no_vue_or_buefy(response)
        self.assertNotIn('<template>', response.content.decode())

    def test_the_icon_tag_replaces_b_icon_for_joyo_readings(self):
        """The one <b-icon> this page had marks a joyo reading; this is a
        weak check (no ExMap fixture set up here) that the tag itself made
        the swap correctly rather than being silently dropped."""
        from kukan.templatetags.icons import icon
        self.assertIn('mdi-check', str(icon('check', size='is-small')))


class YojiDetailTest(DetailPageTestCase):
    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        super().setUp()
        self.yoji = Yoji.objects.create(
            yoji='閲覧', reading='えつらん', meaning='書類などを調べ見ること')

    def test_renders(self):
        response = self.client.get(
            reverse('kukan:yoji_detail', args=[self.yoji.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '閲覧')

    def test_no_vue_or_buefy_remains(self):
        response = self.client.get(
            reverse('kukan:yoji_detail', args=[self.yoji.pk]))
        self.assert_no_vue_or_buefy(response)
        self.assertNotIn('<fr-addrem-anki', response.content.decode())

    def test_the_anki_toggle_is_alpine_driven(self):
        """Replaces Vue's <fr-addrem-anki>: pins that the widget still posts
        to the same ajax endpoint with the same field names, since
        kukan/views.py yoji_anki reads request.POST['yoji']/['op'] directly."""
        response = self.client.get(
            reverse('kukan:yoji_detail', args=[self.yoji.pk]))
        content = response.content.decode()
        self.assertIn('x-data', content)
        self.assertIn(reverse('kukan:yoji_anki'), content)
        self.assertIn("body.set('yoji'", content)
        self.assertIn("body.set('op'", content)

    def test_not_yet_in_anki_shows_the_add_button(self):
        response = self.client.get(
            reverse('kukan:yoji_detail', args=[self.yoji.pk]))
        self.assertContains(response, 'inAnki: false')

    def test_already_in_anki_shows_the_remove_button(self):
        self.yoji.in_anki = True
        self.yoji.save()
        response = self.client.get(
            reverse('kukan:yoji_detail', args=[self.yoji.pk]))
        self.assertContains(response, 'inAnki: true')

    def test_the_yoji_value_is_escaped_for_javascript(self):
        """A yoji containing a quote would otherwise break out of the JS
        string literal it's embedded in."""
        Yoji.objects.filter(pk='閲覧').delete()
        tricky = Yoji.objects.create(
            yoji="閲'", reading='x', meaning='x')
        response = self.client.get(
            reverse('kukan:yoji_detail', args=[tricky.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("body.set('yoji', '閲'')", response.content.decode())
