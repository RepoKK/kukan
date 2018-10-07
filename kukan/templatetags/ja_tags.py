import json
from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escapejs
from kukan.jautils import JpText

register = template.Library()


@register.filter(is_safe=True)
def furigana_html(plain_text, furigana_text):
    """Convert furigana from simple format (square brackets) to html format (ruby tags)"""

    if furigana_text:
        JpText.from_furigana_text(furigana_text)
        res = mark_safe(JpText.from_furigana_text(furigana_text).get_furigana_html())
    else:
        res = plain_text
    return res


@register.inclusion_tag('inclusion/single_field.html')
def render_single_field(field, is_horizontal=False):
    return {'field': field, 'is_horizontal': is_horizontal}


@register.simple_tag(takes_context=True)
def add_vuejs_field_properties(context, form):
    list_vuejs_prop = []
    for name, field in form.fields.items():
        list_vuejs_prop.append("{}: {},".format(name, json.dumps(form[name].value() or '')))
        list_vuejs_prop.append("{}_notifications: {{ items: [], type: 'is-info' }},".format(name))
    return mark_safe('\n'.join(list_vuejs_prop))
