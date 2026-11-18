import re
import secrets
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from care.emr.models import Encounter
from care.emr.models.patient import PatientIdentifier
from django.db import IntegrityError, transaction
from django.utils import timezone

from patient_feedback.models import FeedbackKiosk, FeedbackResponse
from patient_feedback.questionnaire import NO_COMMENT, QUESTION_KEYS, QUESTIONNAIRE_VERSION, normalize_clinics
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


def find_recent_encounter_id(kiosk: FeedbackKiosk, patient_id: int) -> int | None:
    days = int(plugin_settings.ENCOUNTER_LOOKBACK_DAYS)
    if days <= 0:
        return None
    return (
        Encounter.objects.filter(
            patient_id=patient_id,
            facility_id=kiosk.facility_id,
            created_date__gte=timezone.now() - timedelta(days=days),
        )
        .order_by("-created_date")
        .values_list("id", flat=True)
        .first()
    )


# ── Scoring ──────────────────────────────────────────────────────────
def average_rating(ratings: dict) -> Decimal | None:
    scores = [v for k, v in ratings.items() if k in QUESTION_KEYS and isinstance(v, int) and v != NO_COMMENT]
    if not scores:
        return None
    return (Decimal(sum(scores)) / Decimal(len(scores))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Submission ───────────────────────────────────────────────────────
def _reference_number(digits: int) -> str:
    stamp = timezone.localdate().strftime("%Y%m%d")
    number = secrets.randbelow(9 * 10 ** (digits - 1)) + 10 ** (digits - 1)
    return f"{plugin_settings.REFERENCE_PREFIX}-{stamp}-{number}"


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def create_response(kiosk: FeedbackKiosk, draft) -> FeedbackResponse:
    """Persist a finished draft. Reference numbers are unique per facility."""
    data = draft.data
    patient_id = data.get("patient_id") if data.get("uhid") else None
    ratings = {k: v for k, v in data["ratings"].items() if k in QUESTION_KEYS}
    guest = data.get("guest") or {}
    # Store the clinic's English name: readable in reports and stable even if
    # the kiosk's clinic list is edited later.
    clinic_code = guest.get("clinic", "")
    clinic = dict(normalize_clinics(kiosk.clinics)).get(clinic_code, {}).get("en", clinic_code)

    response = FeedbackResponse(
        kiosk=kiosk,
        facility_id=kiosk.facility_id,
        questionnaire_version=QUESTIONNAIRE_VERSION,
        language=data["lang"],
        identification_method=data["method"],
        uhid=data.get("uhid") or "",
        patient_id=patient_id,
        encounter_id=find_recent_encounter_id(kiosk, patient_id) if patient_id else None,
        clinic=clinic,
        age_group=guest.get("age_group", ""),
        sex=guest.get("sex", ""),
        ratings=ratings,
        average_rating=average_rating(ratings),
        would_return=data.get("would_return"),
        would_return_reason=data.get("would_return_reason", ""),
        improvement=data.get("improvement", ""),
        reason_for_choosing=data.get("reason_for_choosing", ""),
        suggestions=data.get("suggestions", ""),
        started_at=_parse_iso(data.get("started_at")),
        submitted_at=timezone.now(),
    )

    # Short, readable reference numbers (OPD-20261118-4821) can collide, so
    # retry; widen the number if a facility ever runs out of 4-digit slots.
    for attempt in range(20):
        response.reference_number = _reference_number(4 if attempt < 12 else 6)
        try:
            with transaction.atomic():
                response.save()
            return response
        except IntegrityError:
            # _base_manager also sees soft-deleted rows, which still hold their number.
            if FeedbackResponse._base_manager.filter(
                facility_id=kiosk.facility_id, reference_number=response.reference_number
            ).exists():
                continue
            raise
    raise RuntimeError("Could not allocate a unique feedback reference number")
