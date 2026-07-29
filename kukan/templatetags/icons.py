"""The `{% icon %}` tag: the HTMX/Alpine replacement for Buefy's `<b-icon>`.

`<b-icon icon="check" size="is-small">` renders a Bulma `.icon` span wrapping
an MDI glyph; this reproduces exactly that markup, so migrating one of the 27
`<b-icon>` uses is a mechanical `{% icon 'check' %}` swap rather than a
redesign.
"""
from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name, size=''):
    classes = f'icon {size}' if size else 'icon'
    return format_html('<span class="{}"><i class="mdi mdi-{}"></i></span>', classes, name)
