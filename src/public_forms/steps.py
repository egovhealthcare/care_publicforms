"""
The questionnaire's steps, worked out on the server.

With JavaScript, kiosk.js moves between the steps in the browser and the page
is posted once. Without it, every step button posts the whole page (every
answer so far is in it, in the hidden steps) together with ``nav``, and the
server shows the step that button leads to. This module is that navigation;
it follows kiosk.js, so both behave the same.

A *unit* is a place in the questionnaire after identification:
``("screen-<n>", 0)`` for the screen of step n's questions, ``("questions", i)``
for rating card i (its place in ``FormSpec.ratings``) and ``("review", 0)``.
They come in step order (questionnaire.py). The identify, scan and UHID
steps come before them.

``nav`` values (the ``value`` of the button pressed):

  go:identify / go:uhid   to that step (from a question or the review: come back to it after)
  guest / uhid            continue without / with the UHID entered; back to where the
                          patient was, via anything that now needs an answer
  next / back             the next / previous unit; ``next`` checks this one first
  edit:<key>              from the review, to that question, then back to the review
  ask:home / ask:reset    Home / Reset in the header: the same place, with the card that asks
                          first (as kiosk.js shows it); Reset with nothing to clear just resets
  reset                   that card's "Yes" for Reset: clear what Reset clears (below) and go
                          to the first rating; the UHID and the details before it stay
  stay                    that card's "No, keep my answers": the same place
  lang:<code>             same step, in that language
  default                 Enter: continue from the UHID step, ``next`` on a question step
  submit                  save (handled by the view)
"""

import re
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

STEPS = ("identify", "scan", "uhid", "questions", "review")  # plus "screen-<n>" for each step's screen
SCREEN_NAME = re.compile(r"screen-([1-9][0-9]?)")
REVIEW = ("review", 0)


def is_flow_step(name) -> bool:
    """A step after identification: a screen of questions, the rating cards or the review."""
    return name in ("questions", "review") or bool(SCREEN_NAME.fullmatch(str(name)))


def shows_home_reset(spec: FormSpec, name) -> bool:
    """Home and Reset show from the first rating on: on cards, the review and "open" screens."""
    if name in ("questions", "review"):
        return True
    screen = spec.group(name)
    return bool(screen and screen.style == "open")


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
    asking: str = ""  # "home" or "reset": that card is open, asking first (without JavaScript)

    @property
    def unit(self) -> tuple[str, int]:
        return (self.step, self.card if self.step == "questions" else 0)

    @property
    def returning(self) -> bool:
        """Changing an answer from the review: the step leads back there (and shows no Back)."""
        return self.return_to == REVIEW


def reset_questions(spec: FormSpec) -> list:
    """What Reset clears: the ratings and the screens after them (those that show Home / Reset)."""
    return [q for screen in spec.screens if screen.is_ratings or screen.style == "open" for q in screen.questions]


def entered(data, questions) -> bool:
    """Any of these questions answered, or a "Why?" typed for one (blank space doesn't count)."""
    return any(str(data.get(key) or "").strip() for q in questions for key in (q.key, comment_key(q)))


def anything_entered(spec: FormSpec, data) -> bool:
    """Something Home would drop: a UHID or any answer (as kiosk.js's anythingEntered)."""
    return bool(str(data.get("uhid") or "").strip()) or entered(data, spec.questions)


def unit_value(unit: tuple[str, int] | None) -> str:
    """A unit as the hidden ``return`` field holds it: "review", "screen-<n>" or "questions:<card>"."""
    if not unit:
        return ""
    return f"questions:{unit[1]}" if unit[0] == "questions" else unit[0]


def parse_unit(value, spec: FormSpec) -> tuple[str, int] | None:
    name, _sep, card = str(value or "").partition(":")
    if name == "review":
        return REVIEW
    if spec.group(name):
        return (name, 0)
    if name != "questions":
        return None
    try:
        index = int(card)
    except ValueError:
        return None
    return (name, index) if 0 <= index < len(spec.ratings) else None


def _rank(spec: FormSpec, unit: tuple[str, int]) -> tuple[int, int]:
    """A unit's position in the full questionnaire, whoever the patient is: (step, place in the step)."""
    name, index = unit
    if name == "questions" and 0 <= index < len(spec.ratings):
        return (spec.ratings[index].step, 1 + index)
    if screen := spec.group(name):
        return (screen.number, 0)
    return (10**6, 0)  # the review, last


def flow_units(spec: FormSpec, identified: bool) -> list[tuple[str, int]]:
    """The places this patient goes through after identification, in order, ending with the review."""
    units, card = [], 0
    for screen in spec.screens:
        if screen.is_ratings:
            for question in screen.questions:
                if applies(question, identified):
                    units.append(("questions", card))
                card += 1
        elif any(applies(question, identified) for question in screen.questions):
            units.append((screen.name, 0))
    units.append(REVIEW)
    return units


def unit_questions(spec: FormSpec, unit: tuple[str, int]) -> list:
    name, index = unit
    if name == "questions":
        return spec.ratings[index : index + 1]
    screen = spec.group(name)
    return screen.questions if screen else []


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
    return here.unit if is_flow_step(here.step) else None


def place_from(data, spec: FormSpec) -> Place:
    """The place the page was on when it was posted (hidden ``step`` / ``card`` / ``return``)."""
    step = data.get("step")
    if step not in STEPS and not spec.group(step):
        step = "identify"
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
        nav = "uhid" if here.step == "uhid" else "next" if here.step == "questions" or spec.group(here.step) else "stay"

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

    if nav == "ask:reset" and not entered(data, reset_questions(spec)):
        nav = "reset"  # nothing to lose
    if nav in ("ask:home", "ask:reset"):
        return Place(here.step, here.card, here.return_to, asking=nav[len("ask:") :]), {}, identified

    units = flow_units(spec, identified)
    position = units.index(here.unit) if here.unit in units else -1

    if nav == "reset":
        for question in reset_questions(spec):
            for key in (question.key, comment_key(question)):
                data.pop(key, None)
        unit = next((unit for unit in units if shows_home_reset(spec, unit[0])), REVIEW)
        return Place(unit[0], unit[1]), {}, identified

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
    for question in [question for screen in spec.screens for question in screen.questions]:
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
