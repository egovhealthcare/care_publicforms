"""Startup checks for the plugin's settings and locale files (shown by `manage.py check` and runserver)."""

from django.core.checks import Warning, register

from public_forms.i18n import BASE_LANGUAGE, RATING_VALUES, catalog, languages, load_problems, placeholders
from public_forms.settings import plugin_settings

MAX_LISTED = 8  # keys named in one warning


def _listed(keys) -> str:
    keys = sorted(keys)
    more = f" and {len(keys) - MAX_LISTED} more" if len(keys) > MAX_LISTED else ""
    return ", ".join(keys[:MAX_LISTED]) + more


@register()
def check_languages(app_configs, **kwargs):
    warnings = []
    entries = catalog()
    for problem in load_problems():
        warnings.append(Warning(f"public_forms locale file can't be read: {problem}", id="public_forms.W003"))
    configured = list(plugin_settings.LANGUAGES or [])
    if unknown := [code for code in configured if code not in entries]:
        warnings.append(
            Warning(
                f"public_forms LANGUAGES has languages without a locale file: {', '.join(unknown)}. "
                "They are not offered.",
                hint=f"Available: {', '.join(entries)}. Add <code>.json to public_forms/locale/ or to a "
                "folder in LOCALE_DIRS (copy en.json and translate it).",
                id="public_forms.W001",
            )
        )
    if plugin_settings.DEFAULT_LANGUAGE not in languages():
        warnings.append(
            Warning(
                f"public_forms DEFAULT_LANGUAGE {plugin_settings.DEFAULT_LANGUAGE!r} is not in LANGUAGES; "
                f"screens start in {next(iter(languages()))!r}.",
                id="public_forms.W002",
            )
        )

    # Offered languages, compared with English: what's missing shows in
    # English; a string whose placeholders differ is replaced by English.
    english = entries.get(BASE_LANGUAGE, {}).get("strings", {})
    for code in languages():
        if code == BASE_LANGUAGE or code not in entries:
            continue
        strings, ratings = entries[code]["strings"], entries[code]["ratings"]
        missing = [key for key in english if not strings.get(key)]
        missing += [f"ratings.{value}" for value in RATING_VALUES if not ratings.get(str(value))]
        if missing:
            warnings.append(
                Warning(
                    f"public_forms {code}: {len(missing)} string(s) not translated, shown in English: "
                    f"{_listed(missing)}.",
                    id="public_forms.W004",
                )
            )
        broken = [
            key
            for key, text in strings.items()
            if key in english and isinstance(text, str) and placeholders(text) != placeholders(english[key])
        ]
        if broken:
            warnings.append(
                Warning(
                    f"public_forms {code}: placeholders such as {{n}} differ from English in {_listed(broken)}; "
                    "these are shown in English.",
                    id="public_forms.W005",
                )
            )
        if unknown_keys := [key for key in strings if key not in english]:
            warnings.append(
                Warning(
                    f"public_forms {code}: unknown string key(s), ignored: {_listed(unknown_keys)}.",
                    hint="Keys must match en.json.",
                    id="public_forms.W006",
                )
            )
    return warnings
