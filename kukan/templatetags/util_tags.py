from django import template
from django.utils.safestring import mark_safe
from kukan.jautils import JpText

register = template.Library()


@register.filter
def add_class(field, class_name):
    return field.as_widget(attrs={
        "class": " ".join((field.css_classes(), class_name))
    })