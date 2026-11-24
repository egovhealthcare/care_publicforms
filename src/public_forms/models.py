import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from public_forms.i18n import BASE_LANGUAGE, localize


class PatientType(models.TextChoices):
    OP = "op", _("Outpatient (OP)")
    IP = "ip", _("Inpatient (IP)")


class QuestionType(models.TextChoices):
    # A question is asked on the page it's listed in (questions.py). Ratings
    # get a card each, on pages of their own; choice, date and text questions
    # share a page, which looks "details" before the first ratings and "open"
    # after them (questionnaire.py). A yes/no question is a choice with the
    # options yes and no.
    RATING = "rating", _("Rating: Poor → Excellent")
    CHOICE = "choice", _("Single choice")
    DATE = "date", _("Date (details)")
    TEXT = "text", _("Free text")


class Audience(models.TextChoices):
    ALL = "all", _("Everyone")
    GUEST = "guest", _("Guests only (no UHID)")
    IDENTIFIED = "identified", _("Patients who gave a UHID")


I18N_HELP = _('Text per language, e.g. {"en": "...", "kn": "..."}.')


class FeedbackForm(models.Model):
    """
    A configurable questionnaire, e.g. the OPD or the inpatient form. Its
    pages are one JSON list (see questions.py), in the order shown, each with
    its questions.

    Every form belongs to one facility, and a facility has at most one form
    per code. The facility is kept by its id: there is no link into Care. A
    form that has submissions can't be deleted, only switched off.
    """

    facility_external_id = models.UUIDField(
        verbose_name=_("facility id"),
        help_text=_("The id of the facility that offers this form (the UUID in its Care URL)."),
    )
    code = models.SlugField(
        max_length=50,
        help_text=_(
            "Short, stable id stored with every response and used in the URL, e.g. 'opd' → "
            "/facility/<id>/public_forms/type/opd/form/."
        ),
    )
    patient_type = models.CharField(max_length=8, choices=PatientType.choices)
    title = models.JSONField(help_text=I18N_HELP)
    description = models.JSONField(default=dict, blank=True, help_text=I18N_HELP)
    pages = models.JSONField(
        default=list,
        blank=True,
        help_text=_("The pages, in the order shown, each with its questions (see below)."),
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0, help_text=_("Order on the form chooser."))

    class Meta:
        db_table = "care_publicforms_form"
        verbose_name = _("feedback form")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility_external_id", "code"],
                name="care_publicforms_form_code_per_facility",
            ),
        ]

    def __str__(self):
        return f"{localize(self.title, BASE_LANGUAGE)} ({self.code})"

    def clean(self):
        if self.pages is None:  # an empty JSON box in a form: no pages yet
            self.pages = []
        errors = {}
        if not isinstance(self.title, dict) or not self.title.get(BASE_LANGUAGE):
            errors["title"] = _("An English title is required.")
        if self.facility_external_id:
            from care.facility.models import Facility

            if not Facility.objects.filter(external_id=self.facility_external_id).exists():
                errors["facility_external_id"] = _("No facility has this id.")
            same_code = FeedbackForm.objects.filter(code=self.code, facility_external_id=self.facility_external_id)
            if same_code.exclude(pk=self.pk).exists():
                errors["code"] = _("This facility already has a form with this code.")
        from public_forms.questions import page_errors  # imports this module

        if problems := page_errors(self.pages):
            errors["pages"] = problems
        if errors:
            raise ValidationError(errors)


class FeedbackSubmission(models.Model):
    """
    One submitted questionnaire, linked to the form it was answered on (the
    only relation; the facility is kept by its id, with no link into Care).
    Every answer carries its own question, so a submission reads the same
    after the form is edited::

        {"registration_wait": {"question": "Waiting time at the registration counter",
                               "type": "rating", "value": 2, "answer": "10-30 mins"},
         "would_return": {"question": "Would you come back…?", "type": "choice",
                          "value": "yes", "answer": "Yes", "comment": "Friendly staff"}}

    ``value``: rating 0 to 5 (0 = "No comments"), choice code, ``YYYY-MM-DD``,
    or text as typed. ``answer`` (ratings and choices): the label picked.
    ``comment`` (choices that ask "Why?"): the reason given. Question and labels are in
    English; the patient's language is ``language``. Questions not answered
    are left out.
    """

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reference_number = models.CharField(max_length=32)
    # Indexed by the constraint and the index below, which both start with it.
    facility_external_id = models.UUIDField()
    # PROTECT: feedback keeps its form; a form with submissions is switched off, not deleted.
    form = models.ForeignKey(FeedbackForm, on_delete=models.PROTECT, related_name="submissions")
    language = models.CharField(max_length=8)
    uhid = models.CharField(max_length=64, blank=True, default="", help_text=_("As entered; empty for guests."))
    answers = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "care_publicforms_submission"
        verbose_name = _("feedback submission")
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility_external_id", "reference_number"],
                name="care_publicforms_submission_reference_per_facility",
            )
        ]
        indexes = [models.Index(fields=["facility_external_id", "form", "submitted_at"])]

    def __str__(self):
        return self.reference_number
