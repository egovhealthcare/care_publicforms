"""Startup checks for the plugin's settings (shown by `manage.py check` and runserver)."""

from django.core.checks import Warning, register

from public_feedback.i18n import KNOWN_LANGUAGES, languages
from public_feedback.settings import plugin_settings


@register()
def check_languages(app_configs, **kwargs):
    warnings = []
    configured = list(plugin_settings.LANGUAGES or [])
    if unknown := [code for code in configured if code not in KNOWN_LANGUAGES]:
        warnings.append(
            Warning(
                f"public_feedback LANGUAGES has languages without screen text: {', '.join(unknown)}. "
                "They are not offered.",
                hint=f"Use {', '.join(KNOWN_LANGUAGES)}, or add the language to KNOWN_LANGUAGES and its "
                "strings in public_feedback/i18n.py.",
                id="public_feedback.W001",
            )
        )
    if plugin_settings.DEFAULT_LANGUAGE not in languages():
        warnings.append(
            Warning(
                f"public_feedback DEFAULT_LANGUAGE {plugin_settings.DEFAULT_LANGUAGE!r} is not in LANGUAGES; "
                f"screens start in {next(iter(languages()))!r}.",
                id="public_feedback.W002",
            )
        )
    return warnings
