import re
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from public_feedback.i18n import BASE_LANGUAGE, localize
from public_feedback.models import FeedbackSubmission, QuestionType
from public_feedback.questionnaire import (
    FormSpec,
    applies,
    choice_labels,
    clean_text,
    comment_key,
    parse_answer,
    rating_labels,
)
from public_feedback.settings import plugin_settings

_NON_DIGITS = re.compile(r"\D")


# ── UHID (format only; it is stored as entered, not looked up) ───────
def uhid_length() -> int:
    return int(plugin_settings.UHID_LENGTH)


def digits_of(value) -> str:
    return _NON_DIGITS.sub("", str(value or ""))


def parse_uhid(raw) -> str | None:
    """
    The UHID if ``raw`` holds exactly UHID_LENGTH digits once every other
    character is dropped (so "123-4567-8901" and "UHID:12345678901" work).
    """
    digits = digits_of(raw)
    return digits if len(digits) == uhid_length() else None


def uhid_groups() -> list[int]:
    groups = [int(g) for g in plugin_settings.UHID_GROUPS or [] if int(g) > 0]
    if sum(groups) != uhid_length():
        return [uhid_length()]
    return groups


# ── Answers ──────────────────────────────────────────────────────────
def stored_answer(question, value, data) -> dict:
    """
    One answer as it is saved: with its question (in English), so the
    submission reads the same after the form changes. ``answer`` is the label
    picked (ratings and choices); ``comment`` the "Why?" of a choice that asks it.
    """
    entry = {"question": localize(question.text, BASE_LANGUAGE), "type": question.type, "value": value}
    if question.type == QuestionType.RATING:
        entry["answer"] = localize(rating_labels(question)[value], BASE_LANGUAGE)
    elif question.type == QuestionType.CHOICE:
        entry["answer"] = localize(choice_labels(question)[value], BASE_LANGUAGE)
        if question.allow_comment and (comment := clean_text(data.get(comment_key(question)))):
            entry["comment"] = comment
    return entry


def collect_answers(spec: FormSpec, data, identified: bool) -> tuple[dict, dict]:
    """
    ``({question_key: stored answer}, {question_key: problem})`` from a submitted
    form, where problem is "required" (no answer) or "invalid" (a date in the
    future or not a date). Questions not meant for this patient (guest-only
    questions when a UHID was given, and the other way round) are ignored, as
    are invalid values of optional questions. Ratings always need an answer.
    """
    answers, missing = {}, {}
    for question in spec.questions:
        if not applies(question, identified):
            continue
        raw = data.get(question.key)
        value = parse_answer(question, raw)
        if value is not None:
            # "Why?" is saved with its yes/no answer; without one it is dropped.
            answers[question.key] = stored_answer(question, value, data)
        elif question.required or question.type == QuestionType.RATING:
            given = question.type == QuestionType.DATE and str(raw or "").strip()
            missing[question.key] = "invalid" if given else "required"
    return answers, missing


# ── Saving ───────────────────────────────────────────────────────────
# reference_number holds 32 characters: prefix (≤ 12) + "-YYYYMMDD-" + up to 6 digits.
MAX_REFERENCE_PREFIX = 12


def _reference_number(digits: int, form_code: str) -> str:
    prefix = (plugin_settings.REFERENCE_PREFIX or form_code.upper())[:MAX_REFERENCE_PREFIX]
    stamp = timezone.localdate().strftime("%Y%m%d")
    number = secrets.randbelow(9 * 10 ** (digits - 1)) + 10 ** (digits - 1)
    return f"{prefix}-{stamp}-{number}"


def create_submission(facility, form, language: str, uhid: str, answers: dict) -> FeedbackSubmission:
    """Save one submission. Reference numbers are unique per facility."""
    submission = FeedbackSubmission(
        facility_external_id=facility.external_id,
        form=form,
        language=language,
        uhid=uhid,
        answers=answers,
    )
    # Short, readable reference numbers (OPD-20261118-4821) can collide, so
    # retry; widen the number if a facility ever runs out of 4-digit slots.
    for attempt in range(20):
        submission.reference_number = _reference_number(4 if attempt < 12 else 6, form.code)
        try:
            with transaction.atomic():
                submission.save()
            return submission
        except IntegrityError:
            if FeedbackSubmission.objects.filter(
                facility_external_id=submission.facility_external_id, reference_number=submission.reference_number
            ).exists():
                continue
            raise
    raise RuntimeError("Could not allocate a unique feedback reference number")
