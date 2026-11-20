"""Startup checks for the plugin's settings and locale files (shown by `manage.py check` and runserver)."""

from django.core.checks import Warning, register

from care_publicforms.i18n import BASE_LANGUAGE, RATING_VALUES, catalog, languages, load_problems, placeholders
from care_publicforms.settings import plugin_settings

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
        warnings.append(Warning(f"care_publicforms locale file can't be read: {problem}", id="care_publicforms.W003"))
    configured = list(plugin_settings.LANGUAGES or [])
    if unknown := [code for code in configured if code not in entries]:
        warnings.append(
            Warning(
                f"care_publicforms LANGUAGES has languages without a locale file: {', '.join(unknown)}. "
                "They are not offered.",
                hint=f"Available: {', '.join(entries)}. Add <code>.json to care_publicforms/locale/ or to a "
                "folder in LOCALE_DIRS (copy en.json and translate it).",
                id="care_publicforms.W001",
            )
        )
    if plugin_settings.DEFAULT_LANGUAGE not in languages():
        warnings.append(
            Warning(
                f"care_publicforms DEFAULT_LANGUAGE {plugin_settings.DEFAULT_LANGUAGE!r} is not in LANGUAGES; "
                f"screens start in {next(iter(languages()))!r}.",
                id="care_publicforms.W002",
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
                    f"care_publicforms {code}: {len(missing)} string(s) not translated, shown in English: "
                    f"{_listed(missing)}.",
                    id="care_publicforms.W004",
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
                    f"care_publicforms {code}: placeholders such as {{n}} differ from English in {_listed(broken)}; "
                    "these are shown in English.",
                    id="care_publicforms.W005",
                )
            )
        if unknown_keys := [key for key in strings if key not in english]:
            warnings.append(
                Warning(
                    f"care_publicforms {code}: unknown string key(s), ignored: {_listed(unknown_keys)}.",
                    hint="Keys must match en.json.",
                    id="care_publicforms.W006",
                )
            )
    return warnings
