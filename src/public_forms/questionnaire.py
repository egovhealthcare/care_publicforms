"""
Turns a configured FeedbackForm into what the feedback page needs.

A form is a list of pages (questions.py), shown in order. A page of ratings
is shown one card per rating; a page of other questions is one screen with
all of them. Within a page, questions keep their order.

A screen of other questions looks one of two ways, by where it is:
  "details"  before the first ratings (or, with no ratings, the first one):
             compact, headed "A few quick details";
  "open"     after the ratings: larger, headed "In your own words", with a
             choice of 2 or 3 options shown as large buttons (a yes/no).
A page's own title replaces the heading, and its own button label the
default one.
"""

from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from public_forms.i18n import default_rating_labels
from public_forms.models import Audience, FeedbackForm, QuestionType
from public_forms.questions import parse_pages, parse_questions
from public_forms.text_rules import MAX_ANSWER_LENGTH, blocked_in, without_control_characters

NO_COMMENT = 0  # the "No comments" rating; default rating labels are in the locale files


def forms_for_facility(facility) -> list[FeedbackForm]:
    """The facility's active forms, in chooser order."""
    return list(FeedbackForm.objects.filter(facility_external_id=facility.external_id, is_active=True))


def question_order(facility_external_id, form_code) -> list[str]:
    """
    Question keys in the order the facility's form asks them now, for showing
    stored answers in a familiar order.
    """
    form = FeedbackForm.objects.filter(facility_external_id=facility_external_id, code=form_code).first()
    return [question.key for question in parse_questions(form.pages)] if form else []


def comment_key(question) -> str:
    return f"{question.key}__comment"


def applies(question, identified: bool) -> bool:
    """Whether a question is asked of a patient who did (or didn't) give a UHID."""
    if question.audience == Audience.GUEST:
        return not identified
    if question.audience == Audience.IDENTIFIED:
        return identified
    return True


@dataclass
class Screen:
    """The questions of one page: rating cards, or one screen of other questions."""

    number: int  # the page's number
    questions: list = field(default_factory=list)
    is_ratings: bool = False
    style: str = "details"  # screens of other questions: "details" or "open" (see the module docstring)
    # The page's own text, per language (screens of other questions only; empty: the default).
    title: dict = field(default_factory=dict)
    description: dict = field(default_factory=dict)
    primary_button: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        """The page's name for a screen of other questions (data-step, the hidden "step" field)."""
        return f"screen-{self.number}"


class FormSpec:
    """A form's active questions, grouped into screens in the order the page asks them."""

    def __init__(self, form: FeedbackForm):
        self.form = form
        self.questions = []
        self.screens = []
        for page in parse_pages(form.pages):
            here = [question for question in page.questions if question.active]
            self.questions += here
            # A page holds ratings or other questions (questions.py checks it); were
            # both ever saved, the other questions come first, then the cards.
            others = [question for question in here if question.type != QuestionType.RATING]
            ratings = [question for question in here if question.type == QuestionType.RATING]
            if others:
                self.screens.append(
                    Screen(
                        page.number,
                        others,
                        title=page.title,
                        description=page.description,
                        primary_button=page.primary_button,
                    )
                )
            if ratings:
                self.screens.append(Screen(page.number, ratings, is_ratings=True))
        first_ratings = next((i for i, screen in enumerate(self.screens) if screen.is_ratings), None)
        groups = [i for i, screen in enumerate(self.screens) if not screen.is_ratings]
        for i in groups:
            before_ratings = first_ratings is not None and i < first_ratings
            first_without_ratings = first_ratings is None and i == groups[0]
            self.screens[i].style = "details" if before_ratings or first_without_ratings else "open"

    @property
    def ratings(self) -> list:
        """Every rating, in the order asked: a rating card's index is its place here."""
        return [question for screen in self.screens if screen.is_ratings for question in screen.questions]

    @property
    def groups(self) -> list:
        """The screens of other questions (choice, date, text), in order."""
        return [screen for screen in self.screens if not screen.is_ratings]

    def group(self, name: str):
        return next((screen for screen in self.groups if screen.name == name), None)

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
    """
    Typed text as it is saved: without control characters, trimmed, at most
    MAX_ANSWER_LENGTH. Line breaks are kept, as "\n" (browsers post "\r\n").
    """
    text = without_control_characters(str(raw or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()[:MAX_ANSWER_LENGTH]
    return text or None


def typed_blocked_characters(question, data) -> str:
    """Blocked characters (text_rules) in what the patient typed for ``question``: its text answer or its "Why?"."""
    typed = []
    if question.type == QuestionType.TEXT:
        typed.append(data.get(question.key))
    elif question.type == QuestionType.CHOICE and question.allow_comment:
        typed.append(data.get(comment_key(question)))
    return "".join(blocked_in(text) for text in typed)


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
