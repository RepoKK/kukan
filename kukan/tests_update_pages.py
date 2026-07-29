"""Contract tests for the two form pages: kotowaza_update and example_update.

PLAN.md calls `example_update.html` the hardest page in the project -- 395
lines, ~230 of Vue: a modal candidate picker, per-kanji reading selects
feeding a hidden field that `ExampleForm.clean()` validates, five ajax
endpoints, caret-insertion helpers, and a delete that assembled its own
`<form>` with `document.createElement`.

It stays a client-side component after the port, and deliberately so: what
those five endpoints return is *values* -- a definition for a textarea,
reading options for a select, furigana to insert at the caret -- not markup.
htmx swaps HTML, which is the wrong shape for every one of them.

So these tests cover what the server is still responsible for: that the form
renders with the right widgets and names, that the values reach Alpine, and
that posting still saves. The JSON endpoints themselves are covered by
`kukan.tests`.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from kukan.forms import ExampleForm, KotowazaForm
from kukan.models import Example, Kotowaza


class LoggedInTestCase(TestCase):
    fixtures = ['baseline', '閲', '覧']

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')


class KotowazaUpdateTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.kotowaza = Kotowaza.objects.create(
            kotowaza='犬も歩けば棒に当たる', yomi='いぬもあるけばぼうにあたる')

    def get(self):
        response = self.client.get(
            reverse('kukan:kotowaza_update', args=[self.kotowaza.pk]))
        self.assertEqual(response.status_code, 200)
        return response

    def test_requires_login(self):
        response = Client().get(
            reverse('kukan:kotowaza_update', args=[self.kotowaza.pk]))
        self.assertEqual(response.status_code, 302)

    def test_no_vue_or_buefy_remains(self):
        content = self.get().content.decode()
        for marker in ['<b-field', '<b-input', '<b-notification', 'v-model',
                       'axios', 'vue_app', 'node_modules', '[[']:
            self.assertNotIn(marker, content, f'{marker} still on the page')

    def test_every_field_renders(self):
        response = self.get()
        for name in ['kotowaza', 'yomi', 'furigana', 'definition']:
            self.assertContains(response, f'name="{name}"')

    def test_current_values_reach_alpine(self):
        """`form|form_values|json_script`, which replaced
        `add_vuejs_field_properties` splicing a JS object literal."""
        response = self.get()
        self.assertContains(response, 'id="form-values"')
        self.assertContains(response, 'application/json')

    def test_posting_saves(self):
        """Furigana is not optional in practice: `KotowazaForm.clean()`
        rejects anything it cannot reconcile with the word and reading, so
        the form has to be posted the way the page's 振り仮名 button fills
        it in."""
        from kukan.jautils import JpnText

        word, yomi = '猿も木から落ちる', 'さるもきからおちる'
        response = self.client.post(
            reverse('kukan:kotowaza_update', args=[self.kotowaza.pk]),
            {'kotowaza': word, 'yomi': yomi,
             'furigana': JpnText.from_text(word, yomi).furigana(),
             'definition': ''})
        self.assertEqual(response.status_code, 302)
        self.kotowaza.refresh_from_db()
        self.assertEqual(self.kotowaza.kotowaza, word)

    def test_field_errors_render_next_to_the_field(self):
        response = self.client.post(
            reverse('kukan:kotowaza_update', args=[self.kotowaza.pk]),
            {'kotowaza': '犬', 'yomi': 'ABC漢字', 'furigana': '',
             'definition': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'help is-danger')


class ExampleUpdateTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.example = Example.objects.create(
            word='閲覧', yomi='エツラン', sentence='資料を閲覧する',
            definition='調べ見ること', is_joyo=False)

    def get(self):
        response = self.client.get(
            reverse('kukan:example_update', args=[self.example.pk]))
        self.assertEqual(response.status_code, 200)
        return response

    def test_requires_login(self):
        response = Client().get(
            reverse('kukan:example_update', args=[self.example.pk]))
        self.assertEqual(response.status_code, 302)

    def test_no_vue_or_buefy_remains(self):
        content = self.get().content.decode()
        for marker in ['<b-field', '<b-input', '<b-select', '<b-modal',
                       '<b-icon', '<b-notification', 'v-model', 'v-for',
                       'v-if', 'axios', 'vue_app', 'node_modules', '[[',
                       '$toast', '$dialog']:
            self.assertNotIn(marker, content, f'{marker} still on the page')

    def test_every_field_renders(self):
        response = self.get()
        for name in ['word', 'word_native', 'word_variation', 'yomi',
                     'yomi_native', 'sentence', 'definition', 'definition2',
                     'ex_kind', 'kotowaza']:
            self.assertContains(response, f'name="{name}"')

    def test_reading_selected_is_a_hidden_field_alpine_fills_in(self):
        """`ExampleForm.clean()` counts the comma-separated entries against
        the kanji in the word, so this name and its encoding are a contract
        between the page and the form."""
        response = self.get()
        self.assertContains(response, 'name="reading_selected"')
        self.assertContains(response, 'readingSelected.join')

    def test_the_definition_fields_are_real_textareas(self):
        """They were `TextInput(attrs={'type': 'textarea'})` -- how Buefy
        asked `<b-input>` for a textarea. Rendered by plain Django that is
        `<input type="textarea">`, which is just a one-line text box."""
        response = self.get()
        self.assertContains(response, '<textarea name="definition"')
        self.assertContains(response, '<textarea name="definition2"')
        self.assertNotContains(response, 'type="textarea"')

    def test_the_select_fields_get_a_bulma_wrapper_not_a_class(self):
        """Bulma styles `<div class="select">` around the element, so a
        `class="select"` on the `<select>` itself would do nothing."""
        response = self.get()
        self.assertContains(response, '<div class="select is-fullwidth">')
        self.assertNotContains(response, '<select name="ex_kind" class="select"')

    def test_delete_is_a_real_form_with_a_csrf_token(self):
        """The Vue page built the form with `document.createElement` and
        hand-copied the token in. A form in the markup gets it from
        `{% templatetag openblock %} csrf_token {% templatetag closeblock %}`."""
        response = self.get()
        self.assertContains(
            response,
            f'action="/example/delete/{self.example.pk}/"')
        # Not a count: the navbar carries its own search and logout forms.
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_delete_actually_deletes(self):
        pk = self.example.pk
        response = self.client.post(reverse('kukan:example_delete', args=[pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Example.objects.filter(pk=pk).exists())

    def test_a_joyo_example_cannot_be_deleted_from_the_page(self):
        self.example.is_joyo = True
        self.example.save()
        self.assertContains(self.get(), 'disabled')

    def test_the_create_page_has_no_delete_button(self):
        response = self.client.get(reverse('kukan:example_add'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '例文削除')

    def test_posting_saves(self):
        from kukan.models import Reading

        reading = Reading.objects.filter(kanji__kanji='閲').first()
        reading2 = Reading.objects.filter(kanji__kanji='覧').first()
        response = self.client.post(
            reverse('kukan:example_update', args=[self.example.pk]),
            {'word': '閲覧', 'word_native': '', 'word_variation': '',
             'yomi': 'エツラン', 'yomi_native': '',
             'sentence': '書類を閲覧する', 'definition': '新しい意味',
             'definition2': '', 'ex_kind': 'KAKI', 'kotowaza': '',
             'reading_selected': f'{reading.pk},{reading2.pk}'})
        self.assertEqual(response.status_code, 302)
        self.example.refresh_from_db()
        self.assertEqual(self.example.definition, '新しい意味')


class FormStylingTest(TestCase):
    """`BulmaModelForm`, which replaced `BForm`."""

    fixtures = ['baseline', '閲', '覧']

    def test_optional_fields_are_marked_in_the_placeholder(self):
        form = KotowazaForm()
        self.assertTrue(
            form.fields['yomi'].widget.attrs['placeholder'].startswith('（任意）'))
        self.assertFalse(
            form.fields['kotowaza'].widget.attrs['placeholder'].startswith('（任意）'))

    def test_a_field_without_its_own_placeholder_falls_back_to_its_label(self):
        form = KotowazaForm()
        self.assertEqual(form.fields['kotowaza'].widget.attrs['placeholder'],
                         form.fields['kotowaza'].label)

    def test_text_widgets_get_the_bulma_input_class(self):
        form = KotowazaForm()
        self.assertIn('input', form.fields['kotowaza'].widget.attrs['class'])
        self.assertIn('textarea',
                      form.fields['definition'].widget.attrs['class'])

    def test_selects_get_neither_a_class_nor_a_placeholder(self):
        form = ExampleForm(instance=None)
        attrs = form.fields['ex_kind'].widget.attrs
        self.assertNotIn('class', attrs)
        self.assertNotIn('placeholder', attrs)

    def test_every_field_is_bound_for_alpine(self):
        form = KotowazaForm()
        for name, field in form.fields.items():
            self.assertEqual(field.widget.attrs['x-model'], name)

    def test_no_field_carries_a_vue_binding(self):
        for form in [KotowazaForm(), ExampleForm(instance=None)]:
            for field in form.fields.values():
                self.assertNotIn('v-model', field.widget.attrs)
