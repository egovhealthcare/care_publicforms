"""
A form's questions: the JSON stored in ``FeedbackForm.questions``.

The questionnaire is a list of objects. ``step`` is a number: the screen
that asks the question. Screens come in the order of their numbers (gaps
are fine), and within a screen the questions keep their order in the list.
A step holds either ratings, shown one card each, or other questions
(choice, date, text), shown together on one screen; not both. Keys with
their default value can be left out::

    [
      {"key": "clinic", "type": "choice", "step": 1, "required": true,
       "text": {"en": "Clinic visited", "kn": "…"},
       "options": [{"value": "ent", "en": "ENT", "kn": "…"}]},
      {"key": "registration_wait", "type": "rating", "step": 2,
       "text": {"en": "Waiting time at the registration counter"},
       "short_text": {"en": "Registration wait"},
       "options": [{"en": "More than 30 mins"}, …five labels, Poor → Excellent]},
      {"key": "would_return", "type": "choice", "step": 3, "allow_comment": true,
       "text": {"en": "Would you come back to this hospital for treatment?"},
       "options": [{"value": "yes", "en": "Yes"}, {"value": "no", "en": "No"}]},
      {"key": "suggestions", "type": "text", "step": 3,
       "text": {"en": "Any other suggestions?"}}
    ]

A screen can have its own heading in the form's step titles (``steps_errors``).

Fields: see ``FIELDS``. Submissions keep their own copy of each question's
wording, so editing, reordering or removing questions never changes old
feedback.
"""

import re
from dataclasses import dataclass, field

from public_forms.i18n import BASE_LANGUAGE
from public_forms.models import Audience, QuestionType
from public_forms.text_rules import (
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

KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")

# A step is a whole number: the screen that asks the question, in order.
MAX_STEP = 99
# The step of a question that doesn't say (the admin writes it in on save):
# the layout the kiosk has always had, details first, then the ratings,
# then the open questions.
DEFAULT_STEPS = {QuestionType.CHOICE: 1, QuestionType.DATE: 1, QuestionType.RATING: 2, QuestionType.TEXT: 3}
# Names the steps had before they were numbered.
STEP_NAMES = {"details": 1, "ratings": 2, "open": 3}


def default_step(kind) -> int | None:
    """The step of a question of type ``kind`` that doesn't say."""
    return DEFAULT_STEPS.get(kind)


def step_number(value) -> int | None:
    """``value`` as a step number (1 to MAX_STEP), from a number or an old step name; None if neither."""
    if isinstance(value, str):
        return STEP_NAMES.get(value)
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_STEP:
        return value
    return None


# field → (default, description); the description is shown in the admin.
FIELDS = {
    "key": (None, "Stable id the answer is stored under, e.g. 'ward_cleanliness'. Required; don't change it."),
    "type": (None, "rating, choice, date or text. Required."),
    "step": (
        None,
        "The screen that asks it, a number: screens come in number order. A step holds either ratings (a card "
        "each) or other questions (choice, date, text: together on one screen), not both. Left out: choice and "
        "date 1, rating 2, text 3; saving writes it in.",
    ),
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
    step: int | None = None  # parse_questions fills in the type's default
    allow_comment: bool = False
    active: bool = True


def parse_questions(raw) -> list[Question]:
    """The questions of a (validated) form, in order, each with its step. Unknown fields are ignored."""
    questions = []
    for item in raw or []:
        if isinstance(item, dict):
            values = {name: item[name] for name in FIELDS if name in item}
            values["step"] = step_number(values.get("step")) or default_step(values.get("type"))
            questions.append(Question(**values))
    return questions


def with_steps(raw):
    """
    ``raw`` with every question's "step" a number: written in (right after
    "type") when it's left out, and an old step name ("details", "ratings",
    "open") turned into its number. Anything else is left for the checks.
    """
    if not isinstance(raw, list):
        return raw
    out = []
    for item in raw:
        if isinstance(item, dict) and default_step(item.get("type")):
            if "step" not in item:
                ordered = {}
                for name, value in item.items():
                    ordered[name] = value
                    if name == "type":
                        ordered["step"] = default_step(value)
                item = ordered
            elif isinstance(item["step"], str) and item["step"] in STEP_NAMES:
                item = {**item, "step": STEP_NAMES[item["step"]]}
        out.append(item)
    return out


def _is_text(value, required=False) -> bool:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        return False
    return bool(value.get(BASE_LANGUAGE, "").strip()) if required else True


def _typed_text_errors(name: str, what: str, text, max_length: int) -> list[str]:
    """text_rules for one piece of a question's text: no blocked or control characters, and its length limit."""
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


def question_errors(raw) -> list[str]:
    """Problems in a form's questions JSON, each naming the question; empty when valid."""
    if not isinstance(raw, list):
        return ["The questions must be a list: [ {…}, {…} ]."]
    errors, seen = [], set()
    placed = []  # (name, type, step) of each question, to check what shares a step
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"Question {position}: must be an object {{…}}.")
            continue
        key = item.get("key")
        name = f"“{key}”" if isinstance(key, str) and key else f"Question {position}"

        if unknown := sorted(set(item) - set(FIELDS)):
            errors.append(f"{name}: unknown field(s) {', '.join(unknown)} (allowed: {', '.join(FIELDS)}).")
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            errors.append(f"{name}: key must be lowercase letters, digits and _, starting with a letter.")
        elif key in seen:
            errors.append(f"{name}: another question already uses this key.")
        else:
            seen.add(key)

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
        step = item.get("step", default_step(kind))
        if "step" in item and not (isinstance(step, int) and not isinstance(step, bool) and 1 <= step <= MAX_STEP):
            errors.append(f"{name}: step must be a whole number from 1 to {MAX_STEP}: the screen that asks it.")
        elif kind in QuestionType.values:
            placed.append((name, kind, step))
        if item.get("allow_comment") and kind != QuestionType.CHOICE:
            errors.append(f"{name}: allow_comment (“Why?”) is for choices only.")
    # Ratings are asked one card each, so a step with ratings holds only ratings.
    rating_steps = {step for _name, kind, step in placed if kind == QuestionType.RATING}
    for name, kind, step in placed:
        if kind != QuestionType.RATING and step in rating_steps:
            errors.append(
                f"{name}: step {step} has ratings, which get a card each; give this {kind} question its own step."
            )
    return errors


# A step's heading, per language (FeedbackForm.steps), and its limits.
STEP_TITLE_FIELDS = {"title": MAX_TITLE_LENGTH, "lead": MAX_DESCRIPTION_LENGTH}


def steps_errors(raw, questions) -> list[str]:
    """
    Problems in a form's step titles: {"<step>": {"title": {...}, "lead": {...}}},
    each for a step that has questions other than ratings (a rating card
    shows its own question). Empty when valid.
    """
    if raw in (None, {}):
        return []
    if not isinstance(raw, dict):
        return ['Step titles must be an object, e.g. {"1": {"title": {"en": "About your visit"}}}.']
    parsed = parse_questions(questions) if isinstance(questions, list) else []
    used = {question.step for question in parsed}
    rating_steps = {question.step for question in parsed if question.type == QuestionType.RATING}
    errors = []
    for key, value in raw.items():
        label = f"Step {key}"
        number = int(key) if isinstance(key, str) and key.isdigit() else None
        if number is None:
            errors.append(f'{label}: the key must be a step number, e.g. "1".')
            continue
        if number not in used:
            errors.append(f"{label}: no question has this step.")
        elif number in rating_steps:
            errors.append(f"{label}: has ratings, whose cards show each question; it takes no title.")
        if not isinstance(value, dict) or not value or set(value) - set(STEP_TITLE_FIELDS):
            errors.append(f'{label}: give a title and/or a lead, e.g. {{"title": {{"en": "…"}}}}.')
            continue
        for text_field, max_length in STEP_TITLE_FIELDS.items():
            if text_field not in value:
                continue
            if not _is_text(value[text_field], required=True):
                errors.append(f'{label}: {text_field} needs English text, e.g. {{"en": "…"}}.')
                continue
            for code, text in value[text_field].items():
                errors += _typed_text_errors(label, f"{text_field} ({code})", text, max_length)
    return errors
