"""
A form's questions: the JSON stored in ``FeedbackForm.questions``.

The questionnaire is a list of objects. ``step`` says which screen asks
each question; the screens always come in the same order (details, then a
card per rating, then open), and within a screen the questions keep their
order in the list. Keys with their default value can be left out::

    [
      {"key": "clinic", "type": "choice", "step": "details", "required": true,
       "text": {"en": "Clinic visited", "kn": "…"},
       "options": [{"value": "ent", "en": "ENT", "kn": "…"}]},
      {"key": "registration_wait", "type": "rating", "step": "ratings",
       "text": {"en": "Waiting time at the registration counter"},
       "short_text": {"en": "Registration wait"},
       "options": [{"en": "More than 30 mins"}, …five labels, Poor → Excellent]},
      {"key": "would_return", "type": "choice", "step": "open", "allow_comment": true,
       "text": {"en": "Would you come back to this hospital for treatment?"},
       "options": [{"value": "yes", "en": "Yes"}, {"value": "no", "en": "No"}]},
      {"key": "suggestions", "type": "text", "step": "open",
       "text": {"en": "Any other suggestions?"}}
    ]

Fields: see ``FIELDS``. Submissions keep their own copy of each question's
wording, so editing, reordering or removing questions never changes old
feedback.
"""

import json
import re
from dataclasses import dataclass, field

from public_forms.i18n import BASE_LANGUAGE
from public_forms.models import Audience, QuestionType
from public_forms.text_rules import (
    MAX_OPTION_LENGTH,
    MAX_OPTION_VALUE_LENGTH,
    MAX_QUESTION_LENGTH,
    MAX_SHORT_TEXT_LENGTH,
    blocked_in,
    spaced,
    without_control_characters,
)

# Length limits of a question's text per language, in FIELDS order.
TEXT_LIMITS = {"text": MAX_QUESTION_LENGTH, "short_text": MAX_SHORT_TEXT_LENGTH, "hint": MAX_QUESTION_LENGTH}

KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")

# The screens a question can be asked on, in the order the patient sees them:
#   details  "A few details", right after identification
#   ratings  one card per question
#   open     "In your own words", just before the review
STEPS = ("details", "ratings", "open")
# The steps each type can be asked on; the first is where it goes when the
# question leaves "step" out (the admin writes it in when the form is saved).
TYPE_STEPS = {
    QuestionType.CHOICE: ("details", "open"),
    QuestionType.DATE: ("details",),
    QuestionType.RATING: ("ratings",),
    QuestionType.TEXT: ("open", "details"),
}


def default_step(kind) -> str | None:
    """Where a question of type ``kind`` is asked when it doesn't say."""
    steps = TYPE_STEPS.get(kind)
    return steps[0] if steps else None


# field → (default, description); the description is shown in the admin.
FIELDS = {
    "key": (None, "Stable id the answer is stored under, e.g. 'ward_cleanliness'. Required; don't change it."),
    "type": (None, "rating, choice, date or text. Required."),
    "step": (
        None,
        "The screen that asks it: details (“A few details”, after identification), ratings (one card per "
        "question) or open (“In your own words”, before the review). rating: ratings. choice: details or open "
        "(on open, 2 or 3 options show as large buttons, e.g. a yes/no question). text: open or details. "
        "date: details. Left out, the type's first one; saving writes it in.",
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
    step: str | None = None  # parse_questions fills in the type's default
    allow_comment: bool = False
    active: bool = True


def parse_questions(raw) -> list[Question]:
    """The questions of a (validated) form, in order, each with its step. Unknown fields are ignored."""
    questions = []
    for item in raw or []:
        if isinstance(item, dict):
            values = {name: item[name] for name in FIELDS if name in item}
            values["step"] = values.get("step") or default_step(values.get("type"))
            questions.append(Question(**values))
    return questions


def with_steps(raw):
    """``raw`` with a "step" written into each question that leaves it out, placed after "type"."""
    if not isinstance(raw, list):
        return raw
    out = []
    for item in raw:
        if isinstance(item, dict) and "step" not in item and default_step(item.get("type")):
            ordered = {}
            for name, value in item.items():
                ordered[name] = value
                if name == "type":
                    ordered["step"] = default_step(value)
            item = ordered if "step" in ordered else {**item, "step": default_step(item.get("type"))}
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
        allowed = TYPE_STEPS.get(kind)
        if allowed and "step" in item and item["step"] not in allowed:
            where = " or ".join(allowed)
            errors.append(f"{name}: a {kind} question is asked on {where}, not {json.dumps(item['step'])}.")
        if item.get("allow_comment") and kind != QuestionType.CHOICE:
            errors.append(f"{name}: allow_comment (“Why?”) is for choices only.")
    return errors
