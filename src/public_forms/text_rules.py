"""
Rules for text that people type: patients' answers on the kiosk, and the
titles, questions and labels staff enter in the admin.

No text may contain characters used to write markup or code, so nothing
typed can carry a script, even into another system that shows it without
escaping. (The pages escape everything they show as well.) Invisible
control characters are dropped, and every text has a length limit.

The admin's sign-in form is the exception: a password may use any character.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# < > (HTML tags), { } (template code), ` (JavaScript) and \ (escapes).
BLOCKED_CHARACTERS = "<>{}`\\"
# Invisible control characters; tab, newline and carriage return are kept.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# A patient's answer to a text question, or the "Why?" under a choice.
MAX_ANSWER_LENGTH = 2000
# Admin text, per language.
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 300
MAX_QUESTION_LENGTH = 300  # a question's text or hint
MAX_SHORT_TEXT_LENGTH = 60  # a question's label on the review step
MAX_OPTION_LENGTH = 100  # a choice's or rating's label
MAX_OPTION_VALUE_LENGTH = 64  # a choice's stored code


def blocked_in(text) -> str:
    """The blocked characters found in ``text``, each once; empty when there are none."""
    text = str(text or "")
    return "".join(character for character in BLOCKED_CHARACTERS if character in text)


def spaced(characters: str = BLOCKED_CHARACTERS) -> str:
    """Characters as people read them in a message: ``"< > { } ` \\"``."""
    return " ".join(characters)


def without_control_characters(text: str) -> str:
    return _CONTROL_CHARACTERS.sub("", text)


def validate_typed_text(value):
    """Form validator for text staff type in the admin."""
    if found := blocked_in(value):
        raise ValidationError(
            _("Don't use these characters: %(characters)s"),
            code="blocked_characters",
            params={"characters": spaced(found)},
        )
    if _CONTROL_CHARACTERS.search(str(value or "")):
        raise ValidationError(_("Remove the invisible control characters."), code="control_characters")
