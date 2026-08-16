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
    """`field` rendered with `class_name` on top of the classes it already has.

    `as_widget(attrs=...)` replaces the widget's attributes rather than merging
    them, so the class the form put there -- `input`, from
    `BulmaModelForm.widget_classes` -- has to be carried across by hand or it
    is dropped and the control silently loses its Bulma styling. The two login
    fields hid that by passing `"input is-rounded"` and re-supplying it
    themselves; anything that passed only a modifier got a bare, unstyled
    widget.
    """
    existing = field.field.widget.attrs.get('class', '')
    classes = ' '.join(part for part in (existing, field.css_classes(), class_name)
                       if part)
    return field.as_widget(attrs={'class': classes})


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


#: How a 読み / 読み(simple) value's trailing parts read on the chip. The
#: encoding carries every option, including the defaults; only the ones that
#: change the search are worth the space.
YOMI_CHIP_MARKERS = {
    '位始': '始',
    '位含': '含',
    '読音': '音',
    '読訓': '訓',
    '常用': '常用',
    '常外': '常外',
}


@register.filter
def chip_caption(value, kind):
    """What a filter chip shows for `value`, rather than the raw query string.

    Most filters store what the user typed, and the chip can show it as-is.
    `yomi` and `yomi-simple` do not: they pack the text together with their
    radio settings as "せい_位始_読音_常全", and putting that on the chip means
    the chip reads as the URL rather than as the search. The Vue bar had a
    per-component `filterDisp` for exactly this; doing it here keeps the
    knowledge of the encoding next to `parse_yomi`, which decodes the same
    string for the panel, instead of splitting it across a template and a
    script.

    Defaults (位致 / 読両 / 常全) are deliberately not shown -- they are what
    the filter does anyway, so naming them makes every chip longer for nothing.
    """
    if not value:
        return ''
    if kind not in ('yomi', 'yomi-simple'):
        return value

    text, *rest = value.split('_')
    markers = [YOMI_CHIP_MARKERS[part] for part in rest
               if part in YOMI_CHIP_MARKERS]
    return f'{text} ({"/".join(markers)})' if markers else text


@register.filter
def has_second_column(elements):
    """Whether a checkbox filter's choices spill into a second column.

    `get_choices` tags each element with `col`, and the checkbox template
    renders one Bulma column per value. The second one must not be emitted
    when it would be empty: two `.column`s split the panel in half whether or
    not both hold anything, so a three-item filter like 種別 would wrap its
    labels inside a half-width column beside a blank one. Buefy guarded the
    same markup with `v-if="col1.length>0"`.
    """
    return any(getattr(elem, 'col', None) == 1 or
               (isinstance(elem, dict) and elem.get('col') == 1)
               for elem in elements or [])


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
