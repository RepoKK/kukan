from django import template
from django.utils.safestring import mark_safe
from kukan.jautils import JpText

register = template.Library()


@register.filter(is_safe=True)
def furigana_simple_to_html(furigana_text):
    """Convert furigana from simple format (square brackets) to html format (ruby tags)"""
    JpText.from_furigana_text(furigana_text)
    return mark_safe(JpText.from_furigana_text(furigana_text).get_furigana_html())