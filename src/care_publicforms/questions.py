"""
A form's questions: the JSON stored in ``FeedbackForm.questions``.

The questionnaire is a list of objects, in the order they are asked; keys
with their default value can be left out::

    [
      {"key": "clinic", "type": "choice", "required": true,
       "text": {"en": "Clinic visited", "kn": "…"},
       "options": [{"value": "ent", "en": "ENT", "kn": "…"}]},
      {"key": "registration_wait", "type": "rating",
       "text": {"en": "Waiting time at the registration counter"},
       "short_text": {"en": "Registration wait"},
       "options": [{"en": "More than 30 mins"}, …five labels, Poor → Excellent]},
      {"key": "would_return", "type": "choice", "step": "open", "allow_comment": true,
       "text": {"en": "Would you come back to this hospital for treatment?"},
       "options": [{"value": "yes", "en": "Yes"}, {"value": "no", "en": "No"}]}
    ]

Fields: see ``FIELDS``. Submissions keep their own copy of each question's
wording, so editing, reordering or removing questions never changes old
feedback.
"""

import re
from dataclasses import dataclass, field

from care_publicforms.i18n import BASE_LANGUAGE
from care_publicforms.models import Audience, QuestionType

KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
STEPS = ("details", "open")  # where a choice is asked

# field → (default, description); the description is shown in the admin.
FIELDS = {
    "key": (None, "Stable id the answer is stored under, e.g. 'ward_cleanliness'. Required; don't change it."),
    "type": (None, "rating, choice, date or text. Required; also decides the step it is asked on."),
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
    "step": (
        "details",
        "choice: details (“A few details”, after identification) or open (“In your own words”, before the "
        "review, as large buttons when it has 2–3 options). A yes/no question is an open choice.",
    ),
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
    step: str = "details"
    allow_comment: bool = False
    active: bool = True


def parse_questions(raw) -> list[Question]:
    """The questions of a (validated) form, in order. Unknown fields are ignored."""
    return [
        Question(**{name: item[name] for name in FIELDS if name in item})
        for item in raw or []
        if isinstance(item, dict)
    ]


def _is_text(value, required=False) -> bool:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        return False
    return bool(value.get(BASE_LANGUAGE, "").strip()) if required else True


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
        for flag in ("required", "allow_no_comment", "allow_comment", "active"):
            if flag in item and not isinstance(item[flag], bool):
                errors.append(f"{name}: {flag} must be true or false.")
        if item.get("audience", "all") not in Audience.values:
            errors.append(f"{name}: audience must be one of {', '.join(Audience.values)}.")

        options = item.get("options", [])
        if not isinstance(options, list) or not all(isinstance(o, dict) for o in options):
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
        if "step" in item and (kind != QuestionType.CHOICE or item["step"] not in STEPS):
            errors.append(f"{name}: step is for choices only: {' or '.join(STEPS)}.")
        if item.get("allow_comment") and kind != QuestionType.CHOICE:
            errors.append(f"{name}: allow_comment (“Why?”) is for choices only.")
    return errors
