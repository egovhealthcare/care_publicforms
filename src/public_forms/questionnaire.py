"""
Turns a configured FeedbackForm into what the feedback page needs.

Questions are grouped by type: choice/date questions are asked together on a
"few details" step, each rating gets its own card, and yes/no and free-text
questions share an "in your own words" step.
"""

from datetime import date

from django.db.models import Q
from django.utils import timezone

from public_forms.i18n import default_rating_labels
from public_forms.models import Audience, FeedbackForm, QuestionType
from public_forms.questions import parse_questions

NO_COMMENT = 0  # the "No comments" rating; default rating labels are in the locale files


def asked_on_open_step(question) -> bool:
    """Free text, and choices marked "step": "open" (e.g. yes/no), go on the "in your own words" step."""
    return question.type == QuestionType.TEXT or (question.type == QuestionType.CHOICE and question.step == "open")


MAX_TEXT_LENGTH = 2000


def forms_for_facility(facility) -> list[FeedbackForm]:
    """
    Active forms for a facility: the shared ones, each replaced by the
    facility's own form with the same code. A facility form that is switched
    off hides that code for the facility; the shared one does not come back.
    """
    candidates = FeedbackForm.objects.filter(
        Q(facility_external_id__isnull=True) | Q(facility_external_id=facility.external_id)
    )
    by_code = {}
    for form in candidates.order_by("order", "id"):
        if form.code not in by_code or form.facility_external_id:
            by_code[form.code] = form
    return sorted((f for f in by_code.values() if f.is_active), key=lambda f: (f.order, f.id))


def question_order(facility_external_id, form_code) -> list[str]:
    """
    Question keys in the order the form asks them now (the facility's own form,
    else the shared one), for showing stored answers in a familiar order.
    """
    candidates = FeedbackForm.objects.filter(code=form_code).filter(
        Q(facility_external_id=facility_external_id) | Q(facility_external_id__isnull=True)
    )
    form = max(candidates, key=lambda form: form.facility_external_id is not None, default=None)
    return [question.key for question in parse_questions(form.questions)] if form else []


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
        self.questions = [question for question in parse_questions(form.questions) if question.active]

    @property
    def details(self):
        return [
            q
            for q in self.questions
            if q.type in (QuestionType.CHOICE, QuestionType.DATE) and not asked_on_open_step(q)
        ]

    @property
    def ratings(self):
        return [q for q in self.questions if q.type == QuestionType.RATING]

    @property
    def open_questions(self):
        return [q for q in self.questions if asked_on_open_step(q)]

    @property
    def rating_count_for_everyone(self) -> int:
        return sum(1 for q in self.ratings if q.audience == Audience.ALL)


def rating_labels(question) -> dict:
    """{value: {"en": ..., ...}} for 5 → 1, then "No comments" if offered."""
    defaults = default_rating_labels()  # from the locale files
    labels = {value: defaults[value] for value in (5, 4, 3, 2, 1)}
    if question.options and len(question.options) == 5:
        # options run Poor → Excellent, i.e. 1 → 5
        labels = {value: question.options[value - 1] for value in (5, 4, 3, 2, 1)}
    if question.allow_no_comment:
        labels[NO_COMMENT] = defaults[NO_COMMENT]
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
    return clean_text(raw)
