from django import template

register = template.Library()


@register.filter
def verbose_name(obj):
    return obj._meta.verbose_name


@register.filter
def verbose_name_plural(obj):
    return obj._meta.verbose_name_plural


@register.simple_tag
def field_name(obj, field):

    return obj._meta.get_field(field).verbose_name.title()


@register.filter(name='get')
def get(o, index):
    try:
        return o[index]
    except:
        return "ERROR my filter get"