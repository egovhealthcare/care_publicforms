import re
import secrets

from care.utils.models.base import BaseModel
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from patient_feedback.i18n import DEFAULT_LANGUAGE, LANGUAGE_CHOICES, localize


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


class PatientType(models.TextChoices):
    OP = "op", _("Outpatient (OP)")
    IP = "ip", _("Inpatient (IP)")


class QuestionType(models.TextChoices):
    # Where a question is asked follows from its type:
    #   choice, date   → "a few details" screen, after identification
    #   rating         → one screen per question
    #   yes_no, text   → "in your own words" screen, before review
    RATING = "rating", _("Rating: Poor → Excellent")
    CHOICE = "choice", _("Single choice (details)")
    DATE = "date", _("Date (details)")
    YES_NO = "yes_no", _("Yes / No")
    TEXT = "text", _("Free text")


class Audience(models.TextChoices):
    ALL = "all", _("Everyone")
    GUEST = "guest", _("Guests only (no UHID)")
    IDENTIFIED = "identified", _("Patients who gave a UHID")


I18N_HELP = _('Text per language, e.g. {"en": "...", "kn": "..."}.')
# Kiosk paths next to /<form code>/ (see pages.py)
RESERVED_FORM_CODES = {"done", "reset", "language"}


class FeedbackForm(BaseModel):
    """
    A configurable questionnaire, e.g. the OPD or the inpatient form.

    Forms without a facility are available everywhere. A facility can have its
    own form with the same code (say, a different clinic list), which then
    replaces the shared one on that facility's kiosks.
    """

    facility = models.ForeignKey(
        "facility.Facility",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Leave empty to offer this form at every facility."),
    )
    code = models.SlugField(
        max_length=50,
        help_text=_(
            "Short, stable id stored with every response and used in the kiosk URL, e.g. 'opd' → "
            "/facility/<id>/patient_feedback/opd/."
        ),
    )
    patient_type = models.CharField(max_length=8, choices=PatientType.choices)
    title = models.JSONField(help_text=I18N_HELP)
    description = models.JSONField(default=dict, blank=True, help_text=I18N_HELP)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0, help_text=_("Order on the kiosk's form chooser."))

    class Meta:
        verbose_name = _("feedback form")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                condition=Q(deleted=False, facility__isnull=False),
                name="patient_feedback_form_code_per_facility",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(deleted=False, facility__isnull=True),
                name="patient_feedback_shared_form_code",
            ),
        ]

    def __str__(self):
        return f"{localize(self.title, DEFAULT_LANGUAGE)} ({self.code})"

    def clean(self):
        errors = {}
        if not isinstance(self.title, dict) or not self.title.get(DEFAULT_LANGUAGE):
            errors["title"] = _("An English title is required.")
        # The unique constraints skip soft-deleted rows, which form validation
        # can't check, so check here.
        same_code = FeedbackForm.objects.filter(code=self.code, facility_id=self.facility_id).exclude(pk=self.pk)
        if self.code in RESERVED_FORM_CODES:
            errors["code"] = _("This code is used by the kiosk's own pages; pick another.")
        elif self.code and same_code.exists():
            errors["code"] = _("Another form already uses this code here.")
        if errors:
            raise ValidationError(errors)


class FeedbackQuestion(BaseModel):
    form = models.ForeignKey(FeedbackForm, on_delete=models.CASCADE, related_name="questions")
    key = models.CharField(
        max_length=64,
        help_text=_("Stable id stored with answers, e.g. 'ward_cleanliness'. Don't change it once answers exist."),
    )
    order = models.PositiveSmallIntegerField(default=0)
    type = models.CharField(max_length=16, choices=QuestionType.choices)
    text = models.JSONField(help_text=I18N_HELP)
    short_text = models.JSONField(default=dict, blank=True, help_text=_("Short label for the review screen."))
    hint = models.JSONField(default=dict, blank=True, help_text=I18N_HELP)
    options = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            'Choice: [{"value": "ent", "en": "ENT", "kn": "..."}, ...]. '
            'Rating (optional): five labels from Poor to Excellent, [{"en": "More than 30 mins", "kn": "..."}, ...].'
        ),
    )
    allow_no_comment = models.BooleanField(default=True, help_text=_("Rating: offer “No comments”."))
    allow_comment = models.BooleanField(default=False, help_text=_("Yes/No: also ask “Why?”."))
    required = models.BooleanField(
        default=False, help_text=_("Ratings always need an answer; this applies to the other types.")
    )
    audience = models.CharField(max_length=16, choices=Audience.choices, default=Audience.ALL)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("feedback question")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["form", "key"], condition=Q(deleted=False), name="patient_feedback_question_key_per_form"
            )
        ]

    def __str__(self):
        return f"{self.form.code}.{self.key}"

    def clean(self):
        errors = {}
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.key or ""):
            errors["key"] = _("Use lowercase letters, digits and underscores, starting with a letter.")
        elif self.form_id and (
            FeedbackQuestion.objects.filter(form_id=self.form_id, key=self.key).exclude(pk=self.pk).exists()
        ):
            errors["key"] = _("Another question in this form already uses this key.")
        if not isinstance(self.text, dict) or not self.text.get(DEFAULT_LANGUAGE):
            errors["text"] = _("English question text is required.")
        options = self.options or []
        if not isinstance(options, list):
            errors["options"] = _("Options must be a list.")
        elif self.type == QuestionType.CHOICE:
            values = [o.get("value") for o in options if isinstance(o, dict)]
            if (
                not options
                or len(values) != len(options)
                or not all(isinstance(o, dict) and o.get("value") and o.get(DEFAULT_LANGUAGE) for o in options)
            ):
                errors["options"] = _('A choice needs options like [{"value": "ent", "en": "ENT"}].')
            elif len(set(values)) != len(values):
                errors["options"] = _("Option values must be unique.")
        elif self.type == QuestionType.RATING and options:
            if len(options) != 5 or not all(isinstance(o, dict) and o.get(DEFAULT_LANGUAGE) for o in options):
                errors["options"] = _("Give exactly five labels, Poor to Excellent, or leave empty.")
        if errors:
            raise ValidationError(errors)


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
    forms = models.ManyToManyField(
        FeedbackForm,
        blank=True,
        related_name="kiosks",
        help_text=_("Forms offered on this screen. Leave empty to offer every active form for the facility."),
    )
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
        help_text=_("Identifier that holds the UHID. When set, UHID responses record the patient's id."),
    )
    require_registered_uhid = models.BooleanField(
        default=False,
        help_text=_("Reject UHIDs that don't match a patient (needs the identifier above)."),
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


class FeedbackSubmission(BaseModel):
    """
    One submitted questionnaire.

    Deliberately has no foreign keys: facility, kiosk, form, patient and
    encounter are stored as plain ids (plus names for reading), and
    ``answers`` keeps each question's wording as it was answered. Editing or
    deleting a form, kiosk or patient never changes a stored submission.
    """

    reference_number = models.CharField(max_length=32)

    facility_external_id = models.UUIDField(db_index=True)
    facility_name = models.CharField(max_length=1000)
    kiosk_external_id = models.UUIDField(null=True, blank=True)
    kiosk_name = models.CharField(max_length=255, blank=True, default="")

    form_external_id = models.UUIDField(null=True, blank=True)
    form_code = models.CharField(max_length=50, db_index=True)
    form_title = models.CharField(max_length=255)
    patient_type = models.CharField(max_length=8, choices=PatientType.choices, db_index=True)
    language = models.CharField(max_length=8)

    identification_method = models.CharField(max_length=16, choices=IdentificationMethod.choices)
    uhid = models.CharField(max_length=64, blank=True, default="")
    patient_external_id = models.UUIDField(null=True, blank=True)
    encounter_external_id = models.UUIDField(null=True, blank=True)

    # [{"key", "type", "question", "value", "display"}, ...] in question order
    answers = models.JSONField(default=list)
    # {rating_question_key: 0..5}; 0 = "No comments"
    ratings = models.JSONField(default=dict)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = _("feedback submission")
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility_external_id", "reference_number"],
                name="patient_feedback_submission_reference_per_facility",
            )
        ]
        indexes = [models.Index(fields=["facility_external_id", "patient_type", "submitted_at"])]

    def __str__(self):
        return self.reference_number
