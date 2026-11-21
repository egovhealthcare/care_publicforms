"""
Screen text for the feedback pages: one JSON file per language.

The plugin's languages are in ``locale/<code>.json`` (``en.json``,
``kn.json``). A deployment can add a language, or correct one, with its own
files in the folders listed in the ``LOCALE_DIRS`` setting; their strings are
merged over the plugin's. A file looks like::

    {
      "language": {"name": "Kannada", "toggle": "ಕನ್ನಡ",
                   "font": "Noto Sans Kannada", "tall_script": true},
      "strings": {"back": "ಹಿಂದೆ", "next": "ಮುಂದೆ", …},
      "ratings": {"5": "ಅತ್ಯುತ್ತಮ", "4": "…", "3": "…", "2": "…", "1": "…", "0": "ಪ್ರತಿಕ್ರಿಯೆ ಇಲ್ಲ"}
    }

``language``: ``name`` for screen readers and the admin; ``toggle`` the header
button; ``font`` a Google Fonts family for the script (null: Figtree covers
it); ``tall_script`` for scripts with tall letters and no capitals (Kannada,
Malayalam, …): small labels aren't uppercased and headings get more line
height. ``strings``: the screen text by key, as in ``en.json``; placeholders
such as ``{n}`` must be kept. ``ratings``: the default rating labels, 5 → 1
and 0 ("No comments"). Missing text falls back to English.

Every page carries its text in all offered languages, so switching language
is instant. Which languages are offered, and in what order, is the LANGUAGES
setting. ``manage.py check`` reports problems in the files (checks.py).
"""

import json
import string
from functools import lru_cache
from pathlib import Path

# Questions and screen text must exist in English; other languages fall back to it.
BASE_LANGUAGE = "en"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"
RATING_VALUES = (5, 4, 3, 2, 1, 0)


# ── Loading the files ─────────────────────────────────────────────────
def locale_dirs() -> tuple[Path, ...]:
    """The plugin's locale folder, then the LOCALE_DIRS setting's, in order."""
    from public_forms.settings import plugin_settings

    return _dirs(tuple(plugin_settings.LOCALE_DIRS or ()))


@lru_cache(maxsize=8)
def _dirs(configured: tuple) -> tuple[Path, ...]:
    return (LOCALE_DIR, *(Path(folder) for folder in configured))


@lru_cache(maxsize=8)
def _load(dirs: tuple[Path, ...]) -> tuple[dict, tuple[str, ...]]:
    """
    ``(catalog, problems)``. The catalog maps a language code to its merged
    ``language``, ``strings``, ``ratings`` and the ``files`` read;
    problems are files that couldn't be read. Cached: restart after editing.
    """
    catalog, problems = {}, []
    for folder in dirs:
        if not folder.is_dir():
            problems.append(f"{folder}: not a folder")
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("not a JSON object")
            except (OSError, ValueError) as error:
                problems.append(f"{path}: {error}")
                continue
            entry = catalog.setdefault(path.stem, {"language": {}, "strings": {}, "ratings": {}, "files": []})
            for part in ("language", "strings", "ratings"):
                if isinstance(data.get(part), dict):
                    entry[part].update(data[part])
            entry["files"].append(str(path))
    return catalog, tuple(problems)


def catalog() -> dict:
    """Every language with a locale file: ``{code: {"language", "strings", "ratings", …}}``."""
    return _load(locale_dirs())[0]


def load_problems() -> tuple[str, ...]:
    return _load(locale_dirs())[1]


# ── Languages ─────────────────────────────────────────────────────────
def known_languages() -> dict:
    """``{code: {"name", "toggle", "font", "tall_script"}}`` for every language with a file."""
    return _known(locale_dirs())


@lru_cache(maxsize=8)
def _known(dirs: tuple[Path, ...]) -> dict:
    known = {}
    for code, entry in _load(dirs)[0].items():
        meta = entry["language"]
        known[code] = {
            "name": meta.get("name") or code,
            "toggle": meta.get("toggle") or code.upper(),
            "font": meta.get("font") or None,
            "tall_script": bool(meta.get("tall_script")),
        }
    return known


def languages() -> dict:
    """The offered languages (the LANGUAGES setting), in order; English if none is usable."""
    from public_forms.settings import plugin_settings

    return _offered(tuple(plugin_settings.LANGUAGES or ()), locale_dirs())


@lru_cache(maxsize=16)
def _offered(configured: tuple, dirs: tuple[Path, ...]) -> dict:
    # Called for every string on a page, so built once per setting. Don't mutate the result.
    known = _known(dirs)
    codes = [code for code in configured if code in known]
    return {code: known[code] for code in dict.fromkeys(codes or [BASE_LANGUAGE])}


def admin_languages() -> dict:
    """Languages with a text box in the admin: English (required) and the offered ones."""
    return {BASE_LANGUAGE: known_languages()[BASE_LANGUAGE], **languages()}


def normalize_language(code: str | None, default: str | None = None) -> str:
    """``code`` if it is offered, else ``default`` if offered, else the first offered language."""
    offered = languages()
    for candidate in (code, default):
        if candidate in offered:
            return candidate
    return next(iter(offered))


# ── Text ──────────────────────────────────────────────────────────────
def localize(value, lang: str) -> str:
    """Pick ``lang`` from a ``{"en": ..., "kn": ...}`` mapping, falling back to English."""
    if isinstance(value, dict):
        return value.get(lang) or value.get(BASE_LANGUAGE) or ""
    return "" if value is None else str(value)


def translate(key: str, lang: str, **params) -> str:
    """
    The screen string ``key`` in ``lang``, with ``params`` filled in. Falls back
    to English when the language lacks it, or when its placeholders don't
    match (a translation typo must not break the page).
    """
    entries = catalog()
    for code in dict.fromkeys((lang, BASE_LANGUAGE)):
        text = entries.get(code, {}).get("strings", {}).get(key)
        if not isinstance(text, str) or not text:
            continue
        if not params:
            return text
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            continue
    return key


def placeholders(text: str) -> set[str]:
    """The ``{name}`` placeholders in a string (empty if it can't be parsed)."""
    try:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
    except ValueError:
        return {"(unbalanced braces)"}


def default_rating_labels() -> dict:
    """``{value: {code: label}}`` for ratings 5 → 1 and 0 ("No comments"), from the locale files."""
    return _rating_labels(locale_dirs())


@lru_cache(maxsize=8)
def _rating_labels(dirs: tuple[Path, ...]) -> dict:
    entries = _load(dirs)[0]
    return {
        value: {
            code: entry["ratings"][str(value)] for code, entry in entries.items() if entry["ratings"].get(str(value))
        }
        for value in RATING_VALUES
    }
