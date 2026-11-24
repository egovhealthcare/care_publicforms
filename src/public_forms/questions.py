"""
A form's pages and their questions: the JSON stored in ``FeedbackForm.pages``.

The questionnaire is a list of pages, in the order the patient sees them.
Each page lists its ``questions`` in the order asked, and can have its own
heading and main-button label. A page holds either ratings, shown one card
each, or other questions (choice, date, text), shown together on one
screen; not both. Fields with their default value can be left out::

    [
      {"title": {"en": "About your visit"},
       "description": {"en": "Two quick questions."},
       "questions": [
         {"key": "clinic", "type": "choice", "required": true,
          "text": {"en": "Clinic visited", "kn": "…"},
          "options": [{"value": "ent", "en": "ENT", "kn": "…"}]}
       ]},
      {"questions": [
         {"key": "registration_wait", "type": "rating",
          "text": {"en": "Waiting time at the registration counter"},
          "short_text": {"en": "Registration wait"},
          "options": [{"en": "More than 30 mins"}, …five labels, Poor → Excellent]}
       ]},
      {"primary_button": {"en": "Check my answers"},
       "questions": [
         {"key": "would_return", "type": "choice", "allow_comment": true,
          "text": {"en": "Would you come back to this hospital for treatment?"},
          "options": [{"value": "yes", "en": "Yes"}, {"value": "no", "en": "No"}]},
         {"key": "suggestions", "type": "text", "text": {"en": "Any other suggestions?"}}
       ]}
    ]

A page without a title gets a default heading; without a button label, the
label follows from what comes next ("Start the questions", "Next" or
"Review answers"). A page of ratings takes neither: each card shows its own
question.

Fields: see ``PAGE_FIELDS`` and ``FIELDS``. Submissions keep their own copy
of each question's wording, so editing, reordering or removing questions
never changes old feedback.
"""

import re
from dataclasses import dataclass, field

from public_forms.i18n import BASE_LANGUAGE
from public_forms.models import Audience, QuestionType
from public_forms.text_rules import (
    MAX_BUTTON_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_OPTION_LENGTH,
    MAX_OPTION_VALUE_LENGTH,
    MAX_QUESTION_LENGTH,
    MAX_SHORT_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
    blocked_in,
    spaced,
    without_control_characters,
)

# Length limits of a question's text per language, in FIELDS order.
TEXT_LIMITS = {"text": MAX_QUESTION_LENGTH, "short_text": MAX_SHORT_TEXT_LENGTH, "hint": MAX_QUESTION_LENGTH}
# Length limits of a page's own text per language.
PAGE_TEXT_LIMITS = {
    "title": MAX_TITLE_LENGTH,
    "description": MAX_DESCRIPTION_LENGTH,
    "primary_button": MAX_BUTTON_LENGTH,
}

KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")

# A page is named by its number, "screen-<n>", of at most two digits (steps.SCREEN_NAME).
MAX_PAGES = 99

# field → (default, description); the descriptions are shown in the admin.
PAGE_FIELDS = {
    "questions": (None, "The page's questions, in the order asked (fields below). Required."),
    "title": ({}, "The page's heading per language. Left out: a default heading."),
    "description": ({}, "A line under the heading, per language."),
    "primary_button": (
        {},
        "The main button's label per language. Left out: “Start the questions”, “Next” or “Review answers”, "
        "by what comes next.",
    ),
}

FIELDS = {
    "key": (None, "Stable id the answer is stored under, e.g. 'ward_cleanliness'. Required; don't change it."),
    "type": (None, "rating, choice, date or text. Required."),
    "text": (None, 'The question per language, e.g. {"en": "…", "kn": "…"}. English is required.'),
    "short_text": ({}, "Shorter label for the review step, per language."),
    "hint": ({}, "Hint under the question, per language."),
    "options": (
        [],
        'choice: [{"value": "ent", "en": "ENT", "kn": "…"}, …]. '
        'rating (optional): five labels, Poor → Excellent, [{"en": "More than 30 mins"}, …].',
    ),
    "required": (False, "Needs an answer (ratings always do)."),
    "audience": ("all", "all, guest (no UHID) or identified (gave a UHID)."),
    "allow_no_comment": (True, "rating: offer “No comments” (stored as 0)."),
    "allow_comment": (False, "choice: also ask “Why?” under the answer."),
    "active": (True, "false: not asked, but kept in the form."),
}


@dataclass(frozen=True)
class Question:
    key: str
    type: str
    text: dict
    short_text: dict = field(default_factory=dict)
    hint: dict = field(default_factory=dict)
    options: list = field(default_factory=list)
    required: bool = False
    audience: str = Audience.ALL
    allow_no_comment: bool = True
    allow_comment: bool = False
    active: bool = True
    page: int = 0  # the number of the page that asks it, from 1 (parse_pages fills it in)


@dataclass(frozen=True)
class Page:
    number: int  # its place in the form, from 1
    questions: list = field(default_factory=list)
    title: dict = field(default_factory=dict)
    description: dict = field(default_factory=dict)
    primary_button: dict = field(default_factory=dict)


def parse_pages(raw) -> list[Page]:
    """The pages of a (validated) form, in order, with their questions. Unknown fields are ignored."""
    pages = []
    for number, item in enumerate(raw if isinstance(raw, list) else [], start=1):
        if not isinstance(item, dict):
            continue
        questions = item.get("questions") if isinstance(item.get("questions"), list) else []
        pages.append(
            Page(
                number,
                [
                    Question(**{name: question[name] for name in FIELDS if name in question}, page=number)
                    for question in questions
                    if isinstance(question, dict)
                ],
                **{name: item[name] for name in PAGE_TEXT_LIMITS if isinstance(item.get(name), dict)},
            )
        )
    return pages


def parse_questions(raw) -> list[Question]:
    """Every question of a (validated) form, page by page, each with its page's number."""
    return [question for page in parse_pages(raw) for question in page.questions]


def _is_text(value, required=False) -> bool:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        return False
    return bool(value.get(BASE_LANGUAGE, "").strip()) if required else True


def _typed_text_errors(name: str, what: str, text, max_length: int) -> list[str]:
    """text_rules for one piece of a form's text: no blocked or control characters, and its length limit."""
    if not isinstance(text, str):
        return []
    errors = []
    if found := blocked_in(text):
        errors.append(f"{name}: {what} can't contain {spaced(found)}.")
    if without_control_characters(text) != text:
        errors.append(f"{name}: {what} has invisible control characters; remove them.")
    if len(text) > max_length:
        errors.append(f"{name}: {what} is longer than {max_length} characters.")
    return errors


def page_errors(raw) -> list[str]:
    """Problems in a form's pages JSON, each naming the page or question; empty when valid."""
    if not isinstance(raw, list):
        return ['The pages must be a list: [ {"questions": [ … ]}, {"questions": [ … ]} ].']
    if len(raw) > MAX_PAGES:
        return [f"A form can have at most {MAX_PAGES} pages."]
    errors, seen = [], set()
    for number, page in enumerate(raw, start=1):
        label = f"Page {number}"
        if isinstance(page, dict) and "questions" not in page and ("key" in page or "type" in page):
            errors.append(
                f"{label}: looks like a question. Questions go inside pages: "
                '[ {"questions": [ {…}, {…} ]}, {"questions": [ … ]} ].'
            )
            continue
        if not isinstance(page, dict):
            errors.append(f'{label}: must be an object, e.g. {{"questions": [ … ]}}.')
            continue
        if unknown := sorted(set(page) - set(PAGE_FIELDS)):
            errors.append(f"{label}: unknown field(s) {', '.join(unknown)} (allowed: {', '.join(PAGE_FIELDS)}).")

        questions = page.get("questions")
        if not isinstance(questions, list) or not questions:
            errors.append(f"{label}: questions must be a list of at least one question: [ {{…}}, {{…}} ].")
            questions = questions if isinstance(questions, list) else []
        kinds = set()
        for position, item in enumerate(questions, start=1):
            if not isinstance(item, dict):
                errors.append(f"{label}, question {position}: must be an object {{…}}.")
                continue
            key = item.get("key")
            name = f"“{key}”" if isinstance(key, str) and key else f"{label}, question {position}"
            errors += _question_errors(name, item)
            if isinstance(key, str) and KEY_PATTERN.fullmatch(key):
                if key in seen:
                    errors.append(f"{name}: another question already uses this key.")
                seen.add(key)
            if item.get("type") in QuestionType.values:
                kinds.add(item["type"])

        # Ratings are asked one card each, so a page with ratings holds only ratings,
        # and each card shows its own question and leads on by itself.
        has_ratings = QuestionType.RATING in kinds
        if has_ratings and (others := sorted(kinds - {QuestionType.RATING})):
            errors.append(
                f"{label}: has ratings, which get a card each; "
                f"move its {' and '.join(others)} questions to a page of their own."
            )
        texts = [name for name in PAGE_TEXT_LIMITS if name in page]
        if has_ratings and texts:
            errors.append(f"{label}: has ratings, whose cards show each question; it takes no {' or '.join(texts)}.")
            continue
        for text_field in texts:
            if not _is_text(page[text_field], required=True):
                errors.append(f'{label}: {text_field} needs English text, e.g. {{"en": "…"}}.')
                continue
            for code, text in page[text_field].items():
                errors += _typed_text_errors(label, f"{text_field} ({code})", text, PAGE_TEXT_LIMITS[text_field])
    return errors


def _question_errors(name: str, item: dict) -> list[str]:
    """Problems in one question (but not whether its key is taken), each starting with ``name``."""
    errors = []
    if "step" in item:
        errors.append(f"{name}: step isn't used any more: a question is asked on the page it's listed in. Remove it.")
    if unknown := sorted(set(item) - set(FIELDS) - {"step"}):
        errors.append(f"{name}: unknown field(s) {', '.join(unknown)} (allowed: {', '.join(FIELDS)}).")
    key = item.get("key")
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        errors.append(f"{name}: key must be lowercase letters, digits and _, starting with a letter.")

    kind = item.get("type")
    if kind not in QuestionType.values:
        errors.append(f"{name}: type must be one of {', '.join(QuestionType.values)}.")
    if not _is_text(item.get("text"), required=True):
        errors.append(f'{name}: text needs the English question, e.g. {{"en": "…"}}.')
    for text_field in ("short_text", "hint"):
        if text_field in item and not _is_text(item[text_field]):
            errors.append(f'{name}: {text_field} must be text per language, e.g. {{"en": "…"}}.')
    for text_field, max_length in TEXT_LIMITS.items():
        if isinstance(item.get(text_field), dict):
            for code, text in item[text_field].items():
                errors += _typed_text_errors(name, f"{text_field} ({code})", text, max_length)
    for flag in ("required", "allow_no_comment", "allow_comment", "active"):
        if flag in item and not isinstance(item[flag], bool):
            errors.append(f"{name}: {flag} must be true or false.")
    if item.get("audience", "all") not in Audience.values:
        errors.append(f"{name}: audience must be one of {', '.join(Audience.values)}.")

    options = item.get("options", [])
    options_listed = isinstance(options, list) and all(isinstance(o, dict) for o in options)
    if not options_listed:
        errors.append(f"{name}: options must be a list of objects.")
    elif kind == QuestionType.CHOICE:
        values = [o.get("value") for o in options]
        if not options:
            errors.append(f'{name}: a choice needs options, e.g. [{{"value": "ent", "en": "ENT"}}].')
        elif not all(isinstance(v, str) and v for v in values):
            errors.append(f"{name}: every option needs a value (a short code, stored with answers).")
        elif len(set(values)) != len(values):
            errors.append(f"{name}: option values must be unique.")
        if any(not str(o.get(BASE_LANGUAGE, "")).strip() for o in options):
            errors.append(f"{name}: every option needs English text.")
    elif kind == QuestionType.RATING and options:
        if len(options) != 5 or any(not str(o.get(BASE_LANGUAGE, "")).strip() for o in options):
            errors.append(f"{name}: give exactly five labels with English text, Poor → Excellent, or none.")
    elif kind in (QuestionType.DATE, QuestionType.TEXT) and options:
        errors.append(f"{name}: a {kind} question has no options.")
    for number, option in enumerate(options if options_listed else [], start=1):
        for code, text in option.items():
            if code == "value":
                errors += _typed_text_errors(name, f"option {number}'s value", text, MAX_OPTION_VALUE_LENGTH)
            else:
                errors += _typed_text_errors(name, f"option {number} ({code})", text, MAX_OPTION_LENGTH)
    if item.get("allow_comment") and kind != QuestionType.CHOICE:
        errors.append(f"{name}: allow_comment (“Why?”) is for choices only.")
    return errors
