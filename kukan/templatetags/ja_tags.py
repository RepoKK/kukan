from django import template
from django.utils.safestring import mark_safe
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
def render_single_field(field):
    return {'field': field}


@register.inclusion_tag('inclusion/single_field_horizontal.html')
def render_single_field_horizontal(field):
    return {'field': field}
