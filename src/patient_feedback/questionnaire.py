"""
Turns a configured FeedbackForm into what the kiosk screens need.

Questions are grouped by type: choice/date questions are asked together on a
"few details" screen, each rating gets its own screen, and yes/no and free
text questions share an "in your own words" screen.
"""

from datetime import date

from django.db.models import Q
from django.utils import timezone

from patient_feedback.i18n import localize, translate
from patient_feedback.models import Audience, FeedbackForm, IdentificationMethod, QuestionType

NO_COMMENT = 0
# Default labels for ratings; a question can override 1–5 with its own.
SCALE = {
    5: {"en": "Excellent", "kn": "ಅತ್ಯುತ್ತಮ"},
    4: {"en": "Very good", "kn": "ತುಂಬಾ ಚೆನ್ನಾಗಿದೆ"},
    3: {"en": "Good", "kn": "ಚೆನ್ನಾಗಿದೆ"},
    2: {"en": "Fair", "kn": "ಸಾಧಾರಣ"},
    1: {"en": "Poor", "kn": "ಕಳಪೆ"},
    NO_COMMENT: {"en": "No comments", "kn": "ಪ್ರತಿಕ್ರಿಯೆ ಇಲ್ಲ"},
}
DETAIL_TYPES = {QuestionType.CHOICE, QuestionType.DATE}
OPEN_TYPES = {QuestionType.YES_NO, QuestionType.TEXT}
MAX_TEXT_LENGTH = 2000


def forms_for_kiosk(kiosk) -> list[FeedbackForm]:
    """
    Active forms offered on a kiosk: the ones picked on the kiosk, or else
    every shared form plus the facility's own. A facility form replaces a
    shared form with the same code.
    """
    if kiosk.forms.exists():
        candidates = kiosk.forms.filter(is_active=True)
    else:
        candidates = FeedbackForm.objects.filter(is_active=True)
    candidates = candidates.filter(Q(facility__isnull=True) | Q(facility_id=kiosk.facility_id))
    by_code = {}
    for form in candidates.order_by("order", "id"):
        if form.code not in by_code or form.facility_id:
            by_code[form.code] = form
    return sorted(by_code.values(), key=lambda f: (f.order, f.id))


def comment_key(question) -> str:
    return f"{question.key}__comment"


class FormSpec:
    """A form's active questions, filtered for how the patient identified."""

    def __init__(self, form: FeedbackForm, method: str | None = None):
        self.form = form
        self.method = method
        self._questions = list(form.questions.filter(is_active=True).order_by("order", "id"))

    def _applies(self, question) -> bool:
        if question.audience == Audience.GUEST:
            return self.method == IdentificationMethod.GUEST
        if question.audience == Audience.IDENTIFIED:
            return self.method in (IdentificationMethod.SCAN, IdentificationMethod.MANUAL)
        return True

    @property
    def questions(self):
        return [q for q in self._questions if self._applies(q)]

    @property
    def details(self):
        return [q for q in self.questions if q.type in DETAIL_TYPES]

    @property
    def ratings(self):
        return [q for q in self.questions if q.type == QuestionType.RATING]

    @property
    def open_questions(self):
        return [q for q in self.questions if q.type in OPEN_TYPES]

    @property
    def rating_count_for_everyone(self) -> int:
        return sum(1 for q in self._questions if q.type == QuestionType.RATING and q.audience == Audience.ALL)


def rating_labels(question) -> dict:
    """{value: {"en": ..., ...}} for 5 → 1, then "No comments" if offered."""
    labels = {value: SCALE[value] for value in (5, 4, 3, 2, 1)}
    if question.options and len(question.options) == 5:
        # options run Poor → Excellent, i.e. 1 → 5
        labels = {value: question.options[value - 1] for value in (5, 4, 3, 2, 1)}
    if question.allow_no_comment:
        labels[NO_COMMENT] = SCALE[NO_COMMENT]
    return labels


def choice_labels(question) -> dict:
    return {str(o["value"]): {k: v for k, v in o.items() if k != "value"} for o in question.options or []}


def clean_text(raw) -> str | None:
    text = str(raw or "").strip()[:MAX_TEXT_LENGTH]
    return text or None


def parse_answer(question, raw):
    """Clean a submitted value for ``question``; returns None when unanswered or invalid."""
    if raw is None:
        return None
    if question.type == QuestionType.RATING:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value in rating_labels(question) else None
    raw = str(raw).strip()
    if question.type == QuestionType.CHOICE:
        return raw if raw in choice_labels(question) else None
    if question.type == QuestionType.DATE:
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            return None
        return value.isoformat() if value <= timezone.localdate() else None
    if question.type == QuestionType.YES_NO:
        return {"yes": True, "no": False}.get(raw)
    return clean_text(raw)


def display_answer(question, value, lang: str) -> str:
    if value is None or value == "":
        return ""
    if question.type == QuestionType.RATING:
        return localize(rating_labels(question).get(value, {}), lang)
    if question.type == QuestionType.CHOICE:
        return localize(choice_labels(question).get(str(value), {"en": str(value)}), lang)
    if question.type == QuestionType.DATE:
        try:
            return date.fromisoformat(value).strftime("%d %b %Y")
        except ValueError:
            return str(value)
    if question.type == QuestionType.YES_NO:
        return translate("yes" if value else "no", lang)
    return str(value)
