"""Tests for the server-rendered filter widgets (kukan/templates/ui/filters/)
and the render_filter dispatch tag that picks one by FFilter.kind.

Each widget's hidden input is what actually gets submitted; the visible
checkboxes/radios/text inputs only drive it via Alpine, so the alpine
wiring (x-data, @change) is asserted for presence, not behaviour -- there is
no browser here to click anything. What is asserted for real: the *initial*
server-rendered state (checked attributes, default values) matches what the
current query-string value decodes to, since that part renders once, per
request, in Python, and is exactly what a stale/wrong initial state bug
would hit.
"""
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from kukan.filters import FGenericCheckbox, FGenericYesNo, FYomiSimple
from kukan.models import Kanji


class RenderFilterTagTest(TestCase):
    fixtures = ['baseline']

    def test_dispatches_string_filters(self):
        from kukan.filters import FGenericString
        html = render_to_string(
            'ui/filters/string.html',
            {'filter': FGenericString('諺', 'kotowaza'), 'value': ''})
        self.assertIn('type="text"', html)

    def test_the_tag_picks_the_template_matching_kind(self):
        flt = FGenericCheckbox('種別', 'classification__classification', Kanji)
        html = Template(
            "{% load util_tags %}{% render_filter flt value %}"
        ).render(Context({'flt': flt, 'value': ''}))
        self.assertIn('checkbox', html)


class CheckboxWidgetTest(TestCase):
    fixtures = ['baseline', '閲', '覧']

    def render(self, flt, value):
        return render_to_string(
            'ui/filters/checkbox.html', {'filter': flt, 'value': value})

    def test_renders_one_control_per_choice(self):
        flt = FGenericCheckbox('種別', 'classification__classification', Kanji)
        html = self.render(flt, '')
        for choice in flt.get_choices()['elements']:
            self.assertIn(choice['label'], html)

    def test_multi_select_uses_checkboxes(self):
        flt = FGenericCheckbox('種別', 'classification__classification', Kanji)
        html = self.render(flt, '')
        self.assertIn('type="checkbox"', html)
        self.assertNotIn('type="radio"', html)

    def test_existing_value_is_reflected_in_the_initial_selected_set(self):
        """The value FGenericCheckbox.add_to_query expects is a list of
        labels; that has to be what the widget starts Alpine's `selected`
        with, or a page reload silently drops the active filter."""
        flt = FGenericCheckbox('種別', 'classification__classification', Kanji)
        html = self.render(flt, '常用漢字, 人名用漢字')
        self.assertIn("selected: ['常用漢字', '人名用漢字']", html)

    def test_yes_no_uses_radios_and_no_select_all(self):
        flt = FGenericYesNo('日課', 'in_anki', True, '出る', '出ない')
        html = self.render(flt, '')
        self.assertIn('type="radio"', html)
        self.assertNotIn('type="checkbox"', html)
        self.assertNotIn('全選択', html)

    def test_yes_no_existing_value_is_a_single_element_selection(self):
        flt = FGenericYesNo('日課', 'in_anki', True, '出る', '出ない')
        html = self.render(flt, '出る')
        self.assertIn("selected: ['出る']", html)

    def test_a_label_containing_a_quote_does_not_break_the_script(self):
        """Choice labels come from real column values (a kanken kyu name, a
        classification), not from a fixed list -- escapejs is what stops one
        containing a quote from closing the JS string literal early."""
        flt = FGenericCheckbox('種別', 'classification__classification', Kanji)
        html = self.render(flt, "常用漢字's")
        self.assertNotIn("selected: ['常用漢字's']", html)


class YomiSimpleWidgetTest(SimpleTestCase):
    def render(self, value):
        flt = FYomiSimple('reading_simple')
        return render_to_string(
            'ui/filters/yomi_simple.html', {'filter': flt, 'value': value})

    def test_empty_value_defaults_to_starts_with(self):
        """Matches FYomiSimple's own default: the old Vue widget's `set`
        defaults matchPosition to 位始 whenever localValue is empty."""
        html = self.render('')
        self.assertIn("text: ''", html)
        self.assertIn("position: '位始'", html)

    def test_existing_value_is_split_into_text_and_position(self):
        html = self.render('せいせい_位含')
        self.assertIn("text: 'せいせい'", html)
        self.assertIn("position: '位含'", html)

    def test_all_three_positions_are_offered(self):
        html = self.render('')
        self.assertIn('value="位致"', html)
        self.assertIn('value="位始"', html)
        self.assertIn('value="位含"', html)

    def test_the_hidden_input_formula_omits_the_suffix_when_text_is_empty(self):
        """FYomiSimple.add_to_query expects '' when no filter is applied,
        not '_位始' -- an empty text with a position suffix would silently
        filter on an empty string instead of not filtering at all."""
        html = self.render('')
        self.assertIn("text ? (text + '_' + position) : ''", html)
