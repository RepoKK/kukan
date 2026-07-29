from django import template
from django.template.loader import render_to_string

register = template.Library()

# One partial per FFilter.kind. kind still holds the old Vue component name
# (e.g. "v-filter-string") -- reused as a dispatch key rather than renamed,
# since it is exactly the distinction a rendering partial needs too.
FILTER_TEMPLATES = {
    'v-filter-string': 'ui/filters/string.html',
    'v-filter-checkbox': 'ui/filters/checkbox.html',
    'v-filter-yomi-simple': 'ui/filters/yomi_simple.html',
}


@register.filter
def add_class(field, class_name):
    return field.as_widget(attrs={
        "class": " ".join((field.css_classes(), class_name))
    })


@register.filter
def get_item(mapping, key):
    """Dict lookup by a variable key.

    `{{ row.field }}` cannot do this: Django's dotted lookup treats `field`
    as a literal name, not a variable, and `row.field` is itself dynamic here
    -- it is whichever column FilteredListView is currently rendering.
    """
    return mapping.get(key, '')


@register.filter
def split_comma_space(value):
    """The inverse of FGenericCheckbox/FGenericYesNo's ", ".join(...) -- the
    encoding a multi-value filter's query-string value round-trips through.
    """
    return value.split(', ') if value else []


@register.filter
def split_once(value, sep):
    """value.split(sep, 1), always returning a 2-element list.

    FYomiSimple/FYomi encode as e.g. "せいせい_位始"; an empty or malformed
    value (no filter applied yet) must not raise, so both halves default to
    the empty string rather than the list being short.
    """
    if not value:
        return ['', '']
    parts = value.split(sep, 1)
    return parts if len(parts) == 2 else [parts[0], '']


@register.simple_tag(takes_context=True)
def render_filter(context, flt, value):
    """Render one active FFilter as a form field, dispatching on flt.kind.

    A tag rather than a per-kind {% include %} in every list template, so
    adding a filter type to a page never means editing that page's template
    -- only FILTER_TEMPLATES, once, here.
    """
    template_name = FILTER_TEMPLATES[flt.kind]
    return render_to_string(
        template_name, {'filter': flt, 'value': value},
        request=context.get('request'))


@register.simple_tag
def query_string_replace(request, **kwargs):
    """The current query string with `kwargs` merged in (or added).

    Used to build sort/page links that keep every active filter: each link
    is a complete, self-contained URL, so htmx needs no `hx-include` to carry
    the rest of the form along with it.
    """
    query = request.GET.copy()
    for key, value in kwargs.items():
        query[key] = value
    return query.urlencode()
