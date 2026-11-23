"""
The questionnaire's steps, worked out on the server.

With JavaScript, kiosk.js moves between the steps in the browser and the page
is posted once. Without it, every step button posts the whole page (every
answer so far is in it, in the hidden steps) together with ``nav``, and the
server shows the step that button leads to. This module is that navigation;
it follows kiosk.js, so both behave the same.

A *unit* is a place in the questionnaire after identification:
``("details", 0)``, ``("questions", i)`` for rating card i, ``("comments", 0)``
and ``("review", 0)``. The identify, scan and UHID steps come before them.

``nav`` values (the ``value`` of the button pressed):

  go:identify / go:uhid   to that step (from a question or the review: come back to it after)
  guest / uhid            continue without / with the UHID entered; back to where the
                          patient was, via anything that now needs an answer
  next / back             the next / previous unit; ``next`` checks this one first
  edit:<key>              from the review, to that question, then back to the review
  lang:<code>             same step, in that language
  default                 Enter: continue from the UHID step, ``next`` on a question step
  submit                  save (handled by the view)
"""

from dataclasses import dataclass

from public_forms.models import QuestionType
from public_forms.questionnaire import (
    FormSpec,
    applies,
    choice_labels,
    clean_text,
    comment_key,
    parse_answer,
    rating_labels,
)
from public_forms.services import collect_answers

STEPS = ("identify", "scan", "uhid", "details", "questions", "comments", "review")
FLOW_STEPS = ("details", "questions", "comments", "review")  # after identification
NAV_STEPS = ("questions", "comments", "review")  # where Home / Reset show
REVIEW = ("review", 0)


@dataclass
class Place:
    """
    Where the patient is, or is going: a step and a card. ``return_to`` is
    where Next leads back to: the review after an answer opened from it, or
    the place the patient left to change their UHID or switch to guest.
    """

    step: str = "identify"
    card: int = 0
    return_to: tuple[str, int] | None = None

    @property
    def unit(self) -> tuple[str, int]:
        return (self.step, self.card if self.step == "questions" else 0)

    @property
    def returning(self) -> bool:
        """Changing an answer from the review: the step leads back there (and shows no Back)."""
        return self.return_to == REVIEW


def unit_value(unit: tuple[str, int] | None) -> str:
    """A unit as the hidden ``return`` field holds it: "review", "details", "comments" or "questions:<card>"."""
    if not unit:
        return ""
    return f"questions:{unit[1]}" if unit[0] == "questions" else unit[0]


def parse_unit(value, spec: FormSpec) -> tuple[str, int] | None:
    name, _sep, card = str(value or "").partition(":")
    if name not in FLOW_STEPS:
        return None
    if name != "questions":
        return (name, 0)
    try:
        index = int(card)
    except ValueError:
        return None
    return (name, index) if 0 <= index < len(spec.ratings) else None


def _rank(spec: FormSpec, unit: tuple[str, int]) -> int:
    """A unit's position in the full questionnaire, whoever the patient is."""
    name, index = unit
    return {"details": 0, "questions": 1 + index, "comments": 1 + len(spec.ratings)}.get(name, 2 + len(spec.ratings))


def flow_units(spec: FormSpec, identified: bool) -> list[tuple[str, int]]:
    units = []
    if any(applies(q, identified) for q in spec.details):
        units.append(("details", 0))
    units += [("questions", i) for i, q in enumerate(spec.ratings) if applies(q, identified)]
    if any(applies(q, identified) for q in spec.open_questions):
        units.append(("comments", 0))
    units.append(REVIEW)
    return units


def unit_questions(spec: FormSpec, unit: tuple[str, int]) -> list:
    name, index = unit
    if name == "details":
        return spec.details
    if name == "questions":
        return spec.ratings[index : index + 1]
    if name == "comments":
        return spec.open_questions
    return []


def unit_problems(spec: FormSpec, data, identified: bool, unit: tuple[str, int]) -> dict:
    """The missing / invalid answers on one unit, as collect_answers reports them."""
    _, missing = collect_answers(spec, data, identified)
    keys = {q.key for q in unit_questions(spec, unit)}
    return {key: problem for key, problem in missing.items() if key in keys}


def first_incomplete(spec: FormSpec, data, identified: bool, before=None) -> tuple[str, int] | None:
    """The first unit (before ``before``, if given) with a question that still needs an answer."""
    _, missing = collect_answers(spec, data, identified)
    for unit in flow_units(spec, identified):
        if before and _rank(spec, unit) >= _rank(spec, before):
            break
        if any(q.key in missing for q in unit_questions(spec, unit)):
            return unit
    return None


def toward(spec: FormSpec, data, identified: bool, target: tuple[str, int]) -> Place:
    """
    The way back to ``target``: the first place before it that needs an answer
    (e.g. age and sex after switching to guest), which then leads on to it;
    else ``target`` itself. A target no longer asked becomes the place after it.
    """
    units = flow_units(spec, identified)
    target = next((unit for unit in units if _rank(spec, unit) >= _rank(spec, target)), REVIEW)
    unit = first_incomplete(spec, data, identified, before=target) or target
    return Place(unit[0], unit[1], target if unit != target else None)


def resume_point(here: Place) -> tuple[str, int] | None:
    """Where to come back to after changing the UHID or switching to guest from ``here``."""
    if here.step == "review":
        return REVIEW
    if here.return_to:
        return here.return_to
    return here.unit if here.step in FLOW_STEPS else None


def place_from(data, spec: FormSpec) -> Place:
    """The place the page was on when it was posted (hidden ``step`` / ``card`` / ``return``)."""
    step = data.get("step") if data.get("step") in STEPS else "identify"
    try:
        card = int(data.get("card") or 0)
    except ValueError:
        card = 0
    card = min(max(card, 0), max(len(spec.ratings) - 1, 0))
    return Place(step, card, parse_unit(data.get("return"), spec))


def navigate(spec: FormSpec, data, nav: str, identified: bool, uhid_valid: bool) -> tuple[Place, dict, bool]:
    """
    ``(place to show, errors, identified)`` after pressing ``nav`` on the posted
    page. ``data`` is a mutable copy of the POST; "guest" clears its UHID.
    """
    here = place_from(data, spec)
    if nav == "default":
        nav = {"uhid": "uhid", "details": "next", "questions": "next", "comments": "next"}.get(here.step, "stay")

    if nav in ("go:identify", "go:uhid", "go:scan"):
        # Leaving a question or the review to identify again: come back to it after.
        return Place("identify" if nav == "go:identify" else "uhid", 0, resume_point(here)), {}, identified

    if nav in ("guest", "uhid"):
        if nav == "guest":
            data["uhid"] = ""
            identified = False
        elif not uhid_valid:
            return Place("uhid", 0, here.return_to), {"uhid": "length"}, identified
        else:
            identified = True
        if here.return_to:
            # Back to where the patient was, every answer kept, via anything that
            # now needs an answer (e.g. age and sex for a guest).
            return toward(spec, data, identified, here.return_to), {}, identified
        unit = flow_units(spec, identified)[0]
        return Place(unit[0], unit[1]), {}, identified

    units = flow_units(spec, identified)
    position = units.index(here.unit) if here.unit in units else -1

    if nav == "next":
        if problems := unit_problems(spec, data, identified, here.unit):
            return here, problems, identified
        if here.return_to:
            return toward(spec, data, identified, here.return_to), {}, identified
        unit = units[position + 1] if position + 1 < len(units) else REVIEW
        return Place(unit[0], unit[1]), {}, identified

    if nav == "back":
        if position <= 0:
            return Place("identify", 0, here.return_to), {}, identified
        unit = units[position - 1]
        return Place(unit[0], unit[1], here.return_to), {}, identified

    if nav.startswith("edit:"):
        key = nav[len("edit:") :]
        for unit in units:
            if any(q.key == key for q in unit_questions(spec, unit)):
                return Place(unit[0], unit[1], REVIEW), {}, identified

    return here, {}, identified  # lang:<code>, stay, or anything unknown


# ── The review, rendered on the server ─────────────────────────────────
def answer_label(question, value):
    """The answer as shown on the review: per-language text, plain text, or None if unanswered."""
    if value is None:
        return None
    if question.type == QuestionType.RATING:
        return rating_labels(question).get(value)
    if question.type == QuestionType.CHOICE:
        return choice_labels(question).get(value)
    if question.type == QuestionType.DATE:
        year, month, day = value.split("-")
        return f"{day}/{month}/{year}"
    return value


def review_rows(spec: FormSpec, data, identified: bool) -> list[dict]:
    """One row per question asked of this patient, in page order (as kiosk.js builds it)."""
    rows = []
    for question in [*spec.details, *spec.ratings, *spec.open_questions]:
        if not applies(question, identified):
            continue
        value = answer_label(question, parse_answer(question, data.get(question.key)))
        note = ""
        if question.allow_comment and value is not None:
            note = clean_text(data.get(comment_key(question))) or ""
            if len(note) > 60:
                note = note[:57] + "…"
        rows.append({"key": question.key, "label": question.short_text or question.text, "value": value, "note": note})
    return rows
