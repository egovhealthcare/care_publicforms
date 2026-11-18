import re
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from patient_feedback.i18n import BASE_LANGUAGE, localize


class PatientType(models.TextChoices):
    OP = "op", _("Outpatient (OP)")
    IP = "ip", _("Inpatient (IP)")


class QuestionType(models.TextChoices):
    # Where a question is asked follows from its type:
    #   choice, date   → "a few details" step, after identification
    #   rating         → one card at a time
    #   yes_no, text   → "in your own words" step, before review
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
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")


class FeedbackForm(models.Model):
    """
    A configurable questionnaire, e.g. the OPD or the inpatient form.

    Forms without a facility are offered everywhere. A facility can have its
    own form with the same code (say, a different clinic list), which then
    replaces the shared one for that facility.
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
            "Short, stable id stored with every response and used in the URL, e.g. 'opd' → "
            "/facility/<id>/type/opd/patient_feedback/."
        ),
    )
    patient_type = models.CharField(max_length=8, choices=PatientType.choices)
    title = models.JSONField(help_text=I18N_HELP)
    description = models.JSONField(default=dict, blank=True, help_text=I18N_HELP)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0, help_text=_("Order on the form chooser."))

    class Meta:
        verbose_name = _("feedback form")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                condition=Q(facility__isnull=False),
                name="patient_feedback_form_code_per_facility",
            ),
            models.UniqueConstraint(
                fields=["code"], condition=Q(facility__isnull=True), name="patient_feedback_shared_form_code"
            ),
        ]

    def __str__(self):
        return f"{localize(self.title, BASE_LANGUAGE)} ({self.code})"

    def clean(self):
        errors = {}
        if not isinstance(self.title, dict) or not self.title.get(BASE_LANGUAGE):
            errors["title"] = _("An English title is required.")
        if FeedbackForm.objects.filter(code=self.code, facility_id=self.facility_id).exclude(pk=self.pk).exists():
            errors["code"] = _("Another form already uses this code here.")
        if errors:
            raise ValidationError(errors)


class FeedbackQuestion(models.Model):
    form = models.ForeignKey(FeedbackForm, on_delete=models.CASCADE, related_name="questions")
    key = models.CharField(
        max_length=64,
        help_text=_(
            "Stable id the answer is stored under, e.g. 'ward_cleanliness'. Don't change it once answers exist."
        ),
    )
    order = models.PositiveSmallIntegerField(default=0)
    type = models.CharField(max_length=16, choices=QuestionType.choices)
    text = models.JSONField(help_text=I18N_HELP)
    short_text = models.JSONField(default=dict, blank=True, help_text=_("Short label for the review step."))
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
            models.UniqueConstraint(fields=["form", "key"], name="patient_feedback_question_key_per_form"),
        ]

    def __str__(self):
        return f"{self.form.code}.{self.key}"

    def clean(self):
        errors = {}
        if not KEY_PATTERN.fullmatch(self.key or ""):
            errors["key"] = _("Use lowercase letters, digits and underscores, starting with a letter.")
        elif "__" in self.key:
            errors["key"] = _("Don't use a double underscore; it is reserved for “Why?” answers.")
        elif (
            self.form_id
            and FeedbackQuestion.objects.filter(form_id=self.form_id, key=self.key).exclude(pk=self.pk).exists()
        ):
            errors["key"] = _("Another question in this form already uses this key.")
        if not isinstance(self.text, dict) or not self.text.get(BASE_LANGUAGE):
            errors["text"] = _("English question text is required.")
        options = self.options or []
        if not isinstance(options, list):
            errors["options"] = _("Options must be a list.")
        elif self.type == QuestionType.CHOICE:
            values = [o.get("value") for o in options if isinstance(o, dict)]
            if (
                not options
                or len(values) != len(options)
                or not all(isinstance(o, dict) and o.get("value") and o.get(BASE_LANGUAGE) for o in options)
            ):
                errors["options"] = _('A choice needs options like [{"value": "ent", "en": "ENT"}].')
            elif len(set(values)) != len(values):
                errors["options"] = _("Option values must be unique.")
        elif self.type == QuestionType.RATING and options:
            if len(options) != 5 or not all(isinstance(o, dict) and o.get(BASE_LANGUAGE) for o in options):
                errors["options"] = _("Give exactly five labels, Poor to Excellent, or leave empty.")
        if errors:
            raise ValidationError(errors)


class FeedbackSubmission(models.Model):
    """
    One submitted questionnaire. No foreign keys, and only what is needed to
    read it back: the facility and form it belongs to and the answers as
    ``{question_key: value}``. Ratings are 0–5 (0 = "No comments"), choices
    their option value, dates ``YYYY-MM-DD``, yes/no ``true``/``false`` (its
    "Why?" text under ``<key>__comment``) and free text as typed. The question
    wording and labels come from the form.
    """

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reference_number = models.CharField(max_length=32)
    facility_external_id = models.UUIDField(db_index=True)
    form_code = models.CharField(max_length=50)
    patient_type = models.CharField(max_length=8, choices=PatientType.choices)
    language = models.CharField(max_length=8)
    uhid = models.CharField(max_length=64, blank=True, default="", help_text=_("As entered; empty for guests."))
    answers = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

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
