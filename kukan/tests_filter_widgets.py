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
import json
import re

from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from kukan.filters import (
    FBushu,
    FGenericCheckbox,
    FGenericDateRange,
    FGenericMinMax,
    FGenericYesNo,
    FYomi,
    FYomiSimple,
)
from kukan.models import Kanji, KoukiBushu


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


class MinMaxWidgetTest(SimpleTestCase):
    def render(self, value):
        flt = FGenericMinMax('画数', 'strokes')
        return render_to_string(
            'ui/filters/min_max.html', {'filter': flt, 'value': value})

    def test_empty_value_defaults_to_exact_mode(self):
        html = self.render('')
        self.assertIn("mode: 'exact'", html)
        self.assertIn("exact: ''", html)
        self.assertIn('exclude: false', html)

    def test_an_exact_value_populates_exact_mode(self):
        html = self.render('5')
        self.assertIn("mode: 'exact'", html)
        self.assertIn("exact: '5'", html)

    def test_an_excluded_exact_value_checks_the_exclude_box(self):
        html = self.render('≠ 5')
        self.assertIn("exact: '5'", html)
        self.assertIn('exclude: true', html)

    def test_a_range_value_populates_range_mode(self):
        html = self.render('5~10')
        self.assertIn("mode: 'range'", html)
        self.assertIn("min: '5'", html)
        self.assertIn("max: '10'", html)

    def test_an_open_ended_range_leaves_the_other_side_blank(self):
        html = self.render('~10')
        self.assertIn("min: ''", html)
        self.assertIn("max: '10'", html)

    def test_an_excluded_range_checks_the_exclude_box(self):
        html = self.render('≠ 5~10')
        self.assertIn("mode: 'range'", html)
        self.assertIn("min: '5'", html)
        self.assertIn("max: '10'", html)
        self.assertIn('exclude: true', html)

    def test_the_hidden_input_formula_prefixes_exclude_correctly(self):
        """FGenericMinMax.add_to_query reads the '≠ ' prefix literally; this
        pins that the JS side reproduces exactly that string, not e.g. '!='."""
        html = self.render('')
        self.assertIn("'≠ ' + this.body", html)


class YomiWidgetTest(SimpleTestCase):
    def render(self, value):
        flt = FYomi()
        return render_to_string(
            'ui/filters/yomi.html', {'filter': flt, 'value': value})

    def test_empty_value_uses_the_old_widgets_own_defaults(self):
        """Matches the old v-filter-yomi.html data(): position 位致 (exact),
        onkun 読両 (both), joyo 常全 (every reading)."""
        html = self.render('')
        self.assertIn("text: ''", html)
        self.assertIn("position: '位致'", html)
        self.assertIn("onkun: '読両'", html)
        self.assertIn("joyo: '常全'", html)

    def test_existing_value_is_split_into_all_four_parts(self):
        html = self.render('せいせい_位始_読音_常用')
        self.assertIn("text: 'せいせい'", html)
        self.assertIn("position: '位始'", html)
        self.assertIn("onkun: '読音'", html)
        self.assertIn("joyo: '常用'", html)

    def test_all_nine_radio_options_are_offered(self):
        html = self.render('')
        for value in ['位致', '位始', '位含', '読両', '読音', '読訓',
                      '常全', '常用', '常外']:
            self.assertIn(f'value="{value}"', html)

    def test_the_hidden_input_joins_all_four_parts_with_underscore(self):
        html = self.render('')
        self.assertIn(
            "text ? [text, position, onkun, joyo].join('_') : ''", html)


class BushuWidgetTest(TestCase):
    def setUp(self):
        KoukiBushu.objects.create(bushu='木', variations='', reading='き',
                                  number=75, kakusu=4)
        KoukiBushu.objects.create(bushu='水', variations='', reading='みず',
                                  number=85, kakusu=4)
        KoukiBushu.objects.create(bushu='口', variations='', reading='くち',
                                  number=30, kakusu=3)

    def render(self, value):
        return render_to_string(
            'ui/filters/bushu.html', {'filter': FBushu(), 'value': value})

    def test_the_choices_are_embedded_as_json_grouped_by_stroke_count(self):
        """json_script, not a hand-built JS array literal: the labels here
        are real kanji radicals, arbitrary Unicode text from the database,
        not a fixed list of ASCII identifiers."""
        html = self.render('')
        self.assertIn('id="bushu-choices"', html)
        script = re.search(
            r'<script id="bushu-choices"[^>]*>(.*?)</script>', html).group(1)
        data = json.loads(script)
        by_strokes = {g['strokeNumber']: set(g['bushu']) for g in data}
        self.assertEqual(by_strokes[4], {'木', '水'})
        self.assertEqual(by_strokes[3], {'口'})

    def test_stroke_range_bounds_the_stepper(self):
        html = self.render('')
        self.assertIn('min: 3', html)
        self.assertIn('max: 4', html)

    def test_existing_value_prefills_the_accumulated_text(self):
        """The value FBushu.add_to_query expects is used as an iterable of
        characters -- the text field's raw content, no separator."""
        html = self.render('木水')
        self.assertIn("text: '木水'", html)

    def test_the_hidden_input_carries_the_accumulated_text_unmodified(self):
        html = self.render('')
        self.assertIn('name="部首"', html)
        self.assertIn(':value="text"', html)


class DateRangeWidgetTest(SimpleTestCase):
    def render(self, value):
        flt = FGenericDateRange('作成', 'created_time')
        return render_to_string(
            'ui/filters/daterange.html', {'filter': flt, 'value': value})

    def escaped(self, s):
        """escapejs turns '-' into \\u002D; assert against its real output
        rather than assuming a date string survives escaping unchanged."""
        from django.utils.html import escapejs
        return escapejs(s)

    def test_empty_value_defaults_to_single_date_mode(self):
        html = self.render('')
        self.assertIn("mode: 'single'", html)
        self.assertIn("date: ''", html)
        self.assertIn('exclude: false', html)

    def test_a_single_date_populates_single_mode(self):
        html = self.render('2024-03-09')
        self.assertIn("mode: 'single'", html)
        self.assertIn(f"date: '{self.escaped('2024-03-09')}'", html)

    def test_an_excluded_date_checks_the_exclude_box(self):
        html = self.render('≠ 2024-03-09')
        self.assertIn(f"date: '{self.escaped('2024-03-09')}'", html)
        self.assertIn('exclude: true', html)

    def test_a_range_populates_range_mode(self):
        html = self.render('2024-03-01~2024-03-31')
        self.assertIn("mode: 'range'", html)
        self.assertIn(f"start: '{self.escaped('2024-03-01')}'", html)
        self.assertIn(f"end: '{self.escaped('2024-03-31')}'", html)

    def test_an_open_ended_range_leaves_the_other_side_blank(self):
        html = self.render('~2024-03-31')
        self.assertIn("start: ''", html)
        self.assertIn(f"end: '{self.escaped('2024-03-31')}'", html)

    def test_uses_native_date_inputs(self):
        """The plan's explicit simplification: no custom calendar widget."""
        html = self.render('')
        self.assertIn('type="date"', html)
        self.assertNotIn('type="datetime', html)

    def test_the_hidden_input_formula_prefixes_exclude_correctly(self):
        html = self.render('')
        self.assertIn("'≠ ' + this.body", html)
