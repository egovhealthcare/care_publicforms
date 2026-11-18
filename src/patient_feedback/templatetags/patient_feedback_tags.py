from django import template

from patient_feedback.i18n import DEFAULT_LANGUAGE, localize, translate

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key, **params):
    """``{% t "hero_title" %}`` — a UI string in the current kiosk language."""
    return translate(key, context.get("lang", DEFAULT_LANGUAGE), **params)


@register.simple_tag(takes_context=True)
def tr(context, value):
    """``{% tr question.text %}`` — pick the current language from a ``{"en": ..., "kn": ...}`` dict."""
    return localize(value, context.get("lang", DEFAULT_LANGUAGE))
