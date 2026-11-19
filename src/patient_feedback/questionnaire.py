"""
Turns a configured FeedbackForm into what the feedback page needs.

Questions are grouped by type: choice/date questions are asked together on a
"few details" step, each rating gets its own card, and yes/no and free-text
questions share an "in your own words" step.
"""

from datetime import date

from django.db.models import Q
from django.utils import timezone

from patient_feedback.i18n import BASE_LANGUAGE, localize
from patient_feedback.models import Audience, FeedbackForm, QuestionType

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


def forms_for_facility(facility) -> list[FeedbackForm]:
    """
    Active forms for a facility: the shared ones, each replaced by the
    facility's own form with the same code. A facility form that is switched
    off hides that code for the facility; the shared one does not come back.
    """
    candidates = FeedbackForm.objects.filter(Q(facility__isnull=True) | Q(facility=facility))
    by_code = {}
    for form in candidates.order_by("order", "id"):
        if form.code not in by_code or form.facility_id:
            by_code[form.code] = form
    return sorted((f for f in by_code.values() if f.is_active), key=lambda f: (f.order, f.id))


def form_for_submission(facility_external_id, form_code) -> FeedbackForm | None:
    """The form a submission was made on: the facility's own, else the shared one."""
    candidates = FeedbackForm.objects.filter(code=form_code).filter(
        Q(facility__external_id=facility_external_id) | Q(facility__isnull=True)
    )
    return max(candidates, key=lambda form: form.facility_id is not None, default=None)


def comment_key(question) -> str:
    return f"{question.key}__comment"


def applies(question, identified: bool) -> bool:
    """Whether a question is asked of a patient who did (or didn't) give a UHID."""
    if question.audience == Audience.GUEST:
        return not identified
    if question.audience == Audience.IDENTIFIED:
        return identified
    return True


class FormSpec:
    """A form's active questions, grouped the way the page asks them."""

    def __init__(self, form: FeedbackForm):
        self.form = form
        self.questions = list(form.questions.filter(is_active=True).order_by("order", "id"))

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
        return sum(1 for q in self.ratings if q.audience == Audience.ALL)


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
    """Clean a submitted value for ``question``; None when unanswered or invalid."""
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


def display_answer(question, value, lang: str = BASE_LANGUAGE) -> str:
    """A stored answer as the patient saw it, e.g. ``4 · Very good`` or ``ENT``."""
    if value is None or value == "":
        return ""
    if question.type == QuestionType.RATING:
        label = rating_labels(question).get(value)
        return f"{value} · {localize(label, lang)}" if label else str(value)
    if question.type == QuestionType.CHOICE:
        label = choice_labels(question).get(str(value))
        return localize(label, lang) if label else str(value)
    if question.type == QuestionType.YES_NO and isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)
