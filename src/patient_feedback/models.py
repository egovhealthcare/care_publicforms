import secrets

from care.utils.models.base import BaseModel
from django.db import models
from django.utils.translation import gettext_lazy as _

from patient_feedback.i18n import DEFAULT_LANGUAGE, LANGUAGE_CHOICES


def generate_access_key() -> str:
    return secrets.token_urlsafe(32)


class ScanMode(models.TextChoices):
    CAMERA = "camera", _("Camera (browser reads the QR code)")
    SCANNER = "scanner", _("USB / Bluetooth QR scanner (keyboard mode)")
    DISABLED = "disabled", _("No QR scanning")


class IdentificationMethod(models.TextChoices):
    SCAN = "scan", _("QR scan")
    MANUAL = "manual", _("UHID typed in")
    GUEST = "guest", _("Guest")


class FeedbackKiosk(BaseModel):
    """
    A screen (usually a touch TV) that collects feedback for one facility.

    The kiosk is opened once with ``?key=<access_key>``; the browser then keeps
    a signed cookie, so the key never has to stay in the address bar.
    Regenerating the key logs every browser using the old one out.
    """

    facility = models.ForeignKey("facility.Facility", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=255, help_text=_("Where the kiosk is, e.g. 'OPD block, ground floor'"))
    is_active = models.BooleanField(default=True)
    access_key = models.CharField(max_length=64, unique=True, default=generate_access_key, editable=False)
    default_language = models.CharField(max_length=8, choices=LANGUAGE_CHOICES, default=DEFAULT_LANGUAGE)
    scan_mode = models.CharField(max_length=16, choices=ScanMode.choices, default=ScanMode.CAMERA)
    show_keypad = models.BooleanField(
        default=True,
        help_text=_("Show an on-screen number pad for the UHID (for screens without a system keyboard)."),
    )
    patient_identifier_config = models.ForeignKey(
        "emr.PatientIdentifierConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Identifier that holds the UHID. When set, UHID responses are linked to the patient."),
    )
    require_registered_uhid = models.BooleanField(
        default=False,
        help_text=_("Reject UHIDs that don't match a patient (needs the identifier above)."),
    )
    clinics = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            'Clinics offered to guests, e.g. [{"en": "General Medicine", "kn": "ಸಾಮಾನ್ಯ ಔಷಧ"}]. '
            "Leave empty for the default list."
        ),
    )
    last_seen_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("feedback kiosk")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.facility.name})"

    def regenerate_access_key(self):
        self.access_key = generate_access_key()
        self.save(update_fields=["access_key", "modified_date"])


class FeedbackResponse(BaseModel):
    """One submitted questionnaire."""

    kiosk = models.ForeignKey(FeedbackKiosk, on_delete=models.PROTECT, related_name="responses")
    facility = models.ForeignKey("facility.Facility", on_delete=models.PROTECT, related_name="+")
    reference_number = models.CharField(max_length=32)
    questionnaire_version = models.CharField(max_length=32)
    language = models.CharField(max_length=8)

    identification_method = models.CharField(max_length=16, choices=IdentificationMethod.choices)
    uhid = models.CharField(max_length=64, blank=True, default="")
    patient = models.ForeignKey("emr.Patient", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    encounter = models.ForeignKey("emr.Encounter", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    # Guest details (only filled for guests)
    clinic = models.CharField(max_length=255, blank=True, default="")
    age_group = models.CharField(max_length=32, blank=True, default="")
    sex = models.CharField(max_length=32, blank=True, default="")

    # {question_key: 0..5}; 0 = "No comments"
    ratings = models.JSONField(default=dict)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)

    would_return = models.BooleanField(null=True, blank=True)
    would_return_reason = models.TextField(blank=True, default="")
    improvement = models.TextField(blank=True, default="")
    reason_for_choosing = models.TextField(blank=True, default="")
    suggestions = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = _("feedback response")
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "reference_number"], name="patient_feedback_unique_reference_per_facility"
            )
        ]
        indexes = [models.Index(fields=["facility", "submitted_at"])]

    def __str__(self):
        return self.reference_number
