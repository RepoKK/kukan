from django import template

register = template.Library()


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
