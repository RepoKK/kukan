import re

from django import template
from django.utils.safestring import mark_safe

from kukan.jautils import JpnText, kat2hir

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
        res = mark_safe(f'<ruby>{plain_text}<rt>{furigana_text.translate(kat2hir)}</rt></ruby>')
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


@register.inclusion_tag('ui/_field.html')
def render_single_field(field, is_horizontal=False):
    return {'field': field, 'is_horizontal': is_horizontal}


@register.filter
def form_values(form):
    """The form's current values, keyed by field name, for `x-data`.

    Replaces `add_vuejs_field_properties`, which emitted the same thing as
    raw JS object-literal lines spliced into a `data()` body. This goes
    through `json_script` instead, so the values are escaped by Django
    rather than by hoping no field contains a quote.

    Every field also gets a `<name>_notifications` list. Those were Buefy
    `<b-notification>` panels driven by the ajax endpoints -- the furigana
    guesser and the similar-word lookup both return per-field messages.
    """
    values = {}
    for name in form.fields:
        values[name] = form[name].value() or ''
        values[f'{name}_notifications'] = {'items': [], 'type': 'is-info'}
    return values
