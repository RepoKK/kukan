import json
from django import template
from django.utils.safestring import mark_safe
from kukan.jautils import JpnText, kat2hir
import re

register = template.Library()


@register.filter(is_safe=True)
def furigana_html(plain_text, furigana_text):
    """Convert furigana from simple format (square brackets) to html format (ruby tags)"""

    if furigana_text:
        jpn_text = JpnText.from_furigana_format(furigana_text, plain_text)
        if not jpn_text.get_furigana_errors():
            res = mark_safe(JpnText.from_furigana_format(furigana_text, plain_text).furigana('ruby'))
        else:
            res = jpn_text.get_furigana_errors()[0]
    else:
        res = plain_text
    return res


@register.filter(is_safe=True)
def add_furigana(plain_text, furigana_text):
    """Add furigana as Ruby HTML on top of text"""

    if furigana_text:
        res = mark_safe('<ruby>{}<rt>{}</rt></ruby>'.format(plain_text, furigana_text.translate(kat2hir)))
    else:
        res = plain_text
    return res


@register.filter(is_safe=True)
def furigana_ruby(sentence):
    """Add furigana as Ruby HTML on top of text"""

    res = mark_safe(re.sub(r'\[(.*?)\|(.*?)\|f\]', '<ruby>{}<rt>{}</rt></ruby>'.format(r'\1', r'\2'), sentence))
    return res


@register.filter(is_safe=True)
def furigana_remove(sentence):
    """Remove furigana, display as simple text"""

    res = re.sub(r'\[(.*?)\|(.*?)\|f\]', '{}'.format(r'\1'), sentence)
    return res


@register.filter(is_safe=True)
def furigana_bracket(sentence):
    """Display furigana inside brackets"""

    res = re.sub(r'\[(.*?)\|(.*?)\|f\]', '{}({})'.format(r'\1', r'\2'), sentence)
    return res


@register.inclusion_tag('inclusion/single_field.html')
def render_single_field(field, is_horizontal=False):
    return {'field': field, 'is_horizontal': is_horizontal}


@register.simple_tag()
def add_vuejs_field_properties(form):
    list_vuejs_prop = []
    for name, field in form.fields.items():
        list_vuejs_prop.append("{}: {},".format(name, json.dumps(form[name].value() or '')))
        list_vuejs_prop.append("{}_notifications: {{ items: [], type: 'is-info' }},".format(name))
    return mark_safe('\n'.join(list_vuejs_prop))
