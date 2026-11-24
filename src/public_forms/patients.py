"""
A patient's UHID from the QR code on their slip.

The QR holds the patient's id in Care (a UUID, alone or inside a link). Care
keeps a UHID as one of the patient's identifiers, defined by an identifier
config. The UHID's config is the active one named UHID_IDENTIFIER ("UHID"
unless set: its display name, or its "system", in any letter case), defined
where UHID_IDENTIFIER_SCOPE says:

- "system": one config, system-wide (no facility), for every facility;
- "facility": the kiosk facility's own config; each facility has its own.

Two active configs with that name in that place are ambiguous: none is used,
and a warning is logged.

Only the UHID leaves this module, never anything else about the patient, and
only in the kiosk's UHID format (UHID_LENGTH digits). A patient without that
identifier, or with a value in another format, is "not found".
"""

import logging
import re
import uuid

from care.emr.models.patient import PatientIdentifier, PatientIdentifierConfig

from public_forms.services import parse_uhid
from public_forms.settings import plugin_settings

logger = logging.getLogger(__name__)

PATIENT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
ACTIVE = "active"  # care.emr.resources.patient_identifier.spec.PatientIdentifierStatus.active
UHID_SCOPES = ("system", "facility")  # UHID_IDENTIFIER_SCOPE (checks.py warns about others)


def patient_id_in(raw) -> uuid.UUID | None:
    """The patient id in what a QR code or scanner gave, e.g. "79e6f401-…" or a link ending in it."""
    found = PATIENT_ID.search(str(raw or ""))
    return uuid.UUID(found.group()) if found else None


def is_uhid_config(config: PatientIdentifierConfig) -> bool:
    """Whether the config is named UHID_IDENTIFIER, by its display name or its system."""
    wanted = str(plugin_settings.UHID_IDENTIFIER or "").strip().casefold()
    names = {str((config.config or {}).get(field) or "").strip().casefold() for field in ("display", "system")}
    return bool(wanted) and wanted in names


def uhid_config(facility) -> PatientIdentifierConfig | None:
    """The identifier config that holds UHIDs at ``facility``, as UHID_IDENTIFIER_SCOPE says; None if none."""
    scope = plugin_settings.UHID_IDENTIFIER_SCOPE
    if scope not in UHID_SCOPES:
        return None
    where = {"facility": facility} if scope == "facility" else {"facility__isnull": True}
    found = [c for c in PatientIdentifierConfig.objects.filter(status=ACTIVE, **where) if is_uhid_config(c)]
    if len(found) > 1:
        logger.warning(
            "%d active patient identifier configs are named %r (%s); set UHID_IDENTIFIER to the system of the "
            "one that holds the UHID.",
            len(found),
            plugin_settings.UHID_IDENTIFIER,
            f"facility {facility.external_id}" if scope == "facility" else "system-wide",
        )
        return None
    return found[0] if found else None


def uhid_of_patient(facility, patient_id) -> str | None:
    """The UHID of the patient with this id, at ``facility``, in the kiosk's format; None if there is none."""
    config = uhid_config(facility)
    if config is None or patient_id is None:
        return None
    value = (
        PatientIdentifier.objects.filter(config=config, patient__external_id=patient_id, patient__deleted=False)
        .values_list("value", flat=True)
        .first()
    )
    return parse_uhid(value) if value else None
