"""
Every UI string is rendered in all configured languages; CSS shows the one
matching ``<html data-lang>`` (see base.html), so switching language in the
browser is instant and keeps everything the patient has entered.
"""

import json

from django import template
from django.utils.html import format_html, format_html_join

from patient_feedback.i18n import DEFAULT_LANGUAGE, LANGUAGES, localize, translate

register = template.Library()


def _all_languages(text_for):
    return format_html_join(
        "", '<span class="l10n l10n--{}" lang="{}">{}</span>', ((code, code, text_for(code)) for code in LANGUAGES)
    )


@register.simple_tag
def t(key, **params):
    """``{% t "hero_title" %}``: a UI string, in every language."""
    return _all_languages(lambda code: translate(key, code, **params))


@register.simple_tag
def tr(value):
    """``{% tr question.text %}``: a ``{"en": ..., "kn": ...}`` value, in every language."""
    return _all_languages(lambda code: localize(value, code))


@register.simple_tag(takes_context=True)
def t_text(context, key, **params):
    """Plain text in the page's starting language, for <title> and similar."""
    return translate(key, context.get("lang", DEFAULT_LANGUAGE), **params)


@register.simple_tag(takes_context=True)
def l10n_attr(context, attribute, key=None, value=None, **params):
    """
    ``{% l10n_attr "placeholder" "open_why" %}``: an attribute in the
    starting language plus ``data-l10n-<attribute>`` with every language,
    which kiosk.js swaps in when the language changes.
    """
    texts = {code: translate(key, code, **params) if key else localize(value, code) for code in LANGUAGES}
    lang = context.get("lang", DEFAULT_LANGUAGE)
    return format_html('{}="{}" data-l10n-{}="{}"', attribute, texts.get(lang, ""), attribute, json.dumps(texts))
