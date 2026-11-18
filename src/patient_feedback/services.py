import re
import secrets
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from care.emr.models import Encounter
from care.emr.models.patient import Patient, PatientIdentifier
from django.db import IntegrityError, transaction
from django.utils import timezone

from patient_feedback.i18n import DEFAULT_LANGUAGE, localize
from patient_feedback.models import FeedbackKiosk, FeedbackSubmission, PatientType, QuestionType
from patient_feedback.questionnaire import NO_COMMENT, FormSpec, comment_key, display_answer
from patient_feedback.settings import plugin_settings

_NON_DIGITS = re.compile(r"\D")


# ── UHID ─────────────────────────────────────────────────────────────
def uhid_length() -> int:
    return int(plugin_settings.UHID_LENGTH)


def digits_of(value) -> str:
    return _NON_DIGITS.sub("", str(value or ""))


def parse_uhid(raw) -> str | None:
    """
    Return the UHID if ``raw`` holds exactly UHID_LENGTH digits once every
    other character is dropped. Applies to typed input and to QR payloads
    (so "123-4567-8901" and "UHID:12345678901" both work).
    """
    digits = digits_of(raw)
    return digits if len(digits) == uhid_length() else None


def uhid_groups() -> list[int]:
    groups = [int(g) for g in plugin_settings.UHID_GROUPS or [] if int(g) > 0]
    if sum(groups) != uhid_length():
        return [uhid_length()]
    return groups


def format_uhid(uhid: str) -> str:
    parts, start = [], 0
    for size in uhid_groups():
        if start >= len(uhid):
            break
        parts.append(uhid[start : start + size])
        start += size
    return " ".join(parts)


def find_patient_id(kiosk: FeedbackKiosk, uhid: str) -> int | None:
    if not kiosk.patient_identifier_config_id:
        return None
    return (
        PatientIdentifier.objects.filter(config_id=kiosk.patient_identifier_config_id, value=uhid)
        .order_by("-modified_date")
        .values_list("patient_id", flat=True)
        .first()
    )


def find_recent_encounter(kiosk: FeedbackKiosk, patient_id: int, patient_type: str):
    """
    (patient external id, encounter external id) for the patient's latest
    encounter at the facility. Inpatient forms look further back (the stay
    may have started days ago) and prefer inpatient encounters.
    """
    patient_external_id = Patient.objects.filter(pk=patient_id).values_list("external_id", flat=True).first()
    inpatient = patient_type == PatientType.IP
    days = int(plugin_settings.IP_ENCOUNTER_LOOKBACK_DAYS if inpatient else plugin_settings.ENCOUNTER_LOOKBACK_DAYS)
    if patient_external_id is None or days <= 0:
        return patient_external_id, None
    encounters = Encounter.objects.filter(
        patient_id=patient_id,
        facility_id=kiosk.facility_id,
        created_date__gte=timezone.now() - timedelta(days=days),
    ).order_by("-created_date")
    encounter_id = None
    if inpatient:
        encounter_id = encounters.filter(encounter_class="imp").values_list("external_id", flat=True).first()
    if encounter_id is None:
        encounter_id = encounters.values_list("external_id", flat=True).first()
    return patient_external_id, encounter_id


# ── Scoring ──────────────────────────────────────────────────────────
def average_rating(ratings: dict) -> Decimal | None:
    scores = [v for v in ratings.values() if isinstance(v, int) and v != NO_COMMENT]
    if not scores:
        return None
    return (Decimal(sum(scores)) / Decimal(len(scores))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Submission ───────────────────────────────────────────────────────
def _reference_number(digits: int, form_code: str) -> str:
    prefix = plugin_settings.REFERENCE_PREFIX or form_code.upper()
    stamp = timezone.localdate().strftime("%Y%m%d")
    number = secrets.randbelow(9 * 10 ** (digits - 1)) + 10 ** (digits - 1)
    return f"{prefix}-{stamp}-{number}"


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def build_answers(spec: FormSpec, answers: dict) -> tuple[list, dict]:
    """
    Snapshot of every question the patient was asked, in English, plus the
    ratings as {key: value}. The wording is stored with the answer so later
    edits to the form don't change what this submission meant.
    """
    snapshot, ratings = [], {}
    for question in spec.questions:
        value = answers.get(question.key)
        entry = {
            "key": question.key,
            "type": question.type,
            "question": localize(question.text, DEFAULT_LANGUAGE),
            "label": localize(question.short_text, DEFAULT_LANGUAGE) or localize(question.text, DEFAULT_LANGUAGE),
            "value": value,
            "display": display_answer(question, value, DEFAULT_LANGUAGE),
        }
        if question.type == QuestionType.YES_NO and question.allow_comment:
            entry["comment"] = answers.get(comment_key(question), "")
        if question.type == QuestionType.RATING and isinstance(value, int):
            ratings[question.key] = value
        snapshot.append(entry)
    return snapshot, ratings


def create_submission(kiosk: FeedbackKiosk, spec: FormSpec, draft) -> FeedbackSubmission:
    """Persist a finished draft. Reference numbers are unique per facility."""
    data = draft.data
    form = spec.form
    answers, ratings = build_answers(spec, data["answers"])
    patient_external_id = encounter_external_id = None
    if data.get("uhid") and data.get("patient_id"):
        patient_external_id, encounter_external_id = find_recent_encounter(kiosk, data["patient_id"], form.patient_type)

    submission = FeedbackSubmission(
        facility_external_id=kiosk.facility.external_id,
        facility_name=kiosk.facility.name,
        kiosk_external_id=kiosk.external_id,
        kiosk_name=kiosk.name,
        form_external_id=form.external_id,
        form_code=form.code,
        form_title=localize(form.title, DEFAULT_LANGUAGE)[:255],
        patient_type=form.patient_type,
        language=data["lang"],
        identification_method=data["method"],
        uhid=data.get("uhid") or "",
        patient_external_id=patient_external_id,
        encounter_external_id=encounter_external_id,
        answers=answers,
        ratings=ratings,
        average_rating=average_rating(ratings),
        started_at=_parse_iso(data.get("started_at")),
        submitted_at=timezone.now(),
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
            # _base_manager also sees soft-deleted rows, which still hold their number.
            if FeedbackSubmission._base_manager.filter(
                facility_external_id=submission.facility_external_id,
                reference_number=submission.reference_number,
            ).exists():
                continue
            raise
    raise RuntimeError("Could not allocate a unique feedback reference number")
