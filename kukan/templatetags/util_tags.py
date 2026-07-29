from django import template
from django.template.loader import render_to_string

register = template.Library()

# One partial per FFilter.kind. `kind` used to name a Vue component
# ("v-filter-string"); with the Vue filter bar deleted it is purely the key
# this table dispatches on, so the prefix went with it. Adding a filter type
# to a page means adding a row here, not editing that page's template.
FILTER_TEMPLATES = {
    'string': 'ui/filters/string.html',
    'checkbox': 'ui/filters/checkbox.html',
    'yomi-simple': 'ui/filters/yomi_simple.html',
    'min-max': 'ui/filters/min_max.html',
    'yomi': 'ui/filters/yomi.html',
    'bushu': 'ui/filters/bushu.html',
    'daterange': 'ui/filters/daterange.html',
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


@register.filter
def parse_minmax(value):
    """Decode FGenericMinMax's encoding ("5", "≠ 5", "5~10", "~10",
    "5~", "≠ 5~10") into its parts, for the widget's initial state."""
    exclude = value.startswith('≠ ')
    if exclude:
        value = value[2:]
    if '~' in value:
        lo, hi = value.split('~', 1)
        return {'exclude': exclude, 'mode': 'range', 'exact': '',
                'min': lo, 'max': hi}
    return {'exclude': exclude, 'mode': 'exact', 'exact': value,
            'min': '', 'max': ''}


@register.filter
def parse_yomi(value):
    """Decode FYomi's 4-part encoding ("せいせい_位致_読両_常全"). Defaults
    match the old Vue widget's own defaults for an empty/malformed value."""
    defaults = {'text': '', 'position': '位致', 'onkun': '読両', 'joyo': '常全'}
    if not value:
        return defaults
    parts = value.split('_')
    if len(parts) != 4:
        return defaults
    text, position, onkun, joyo = parts
    return {'text': text, 'position': position, 'onkun': onkun, 'joyo': joyo}


@register.filter
def parse_daterange(value):
    """Decode FGenericDateRange's encoding ("2024-03-09", "≠ 2024-03-09",
    "2024-03-01~2024-03-31", "~2024-03-31", "2024-03-01~") into its parts.

    The widget only offers date-level granularity (a native
    <input type="date">, per the plan's explicit simplification) even though
    FGenericDateRange also accepts a "YYYY-MM-DD HH:MM" half -- an existing
    value with a time component simply will not populate a date input, which
    is the one corner this format-level simplification does not round-trip.
    """
    exclude = value.startswith('≠ ')
    if exclude:
        value = value[2:]
    if '~' in value:
        lo, hi = value.split('~', 1)
        return {'exclude': exclude, 'mode': 'range', 'date': '',
                'start': lo, 'end': hi}
    return {'exclude': exclude, 'mode': 'single', 'date': value,
            'start': '', 'end': ''}


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
