import csv
from contextvars import ContextVar

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from patient_feedback.i18n import DEFAULT_LANGUAGE, LANGUAGES, localize
from patient_feedback.models import FeedbackForm, FeedbackKiosk, FeedbackQuestion, FeedbackSubmission
from patient_feedback.questionnaire import forms_for_kiosk

# The admin's readonly-field callables only receive the object; this lets the
# kiosk link use the host the admin is being served from.
_current_request: ContextVar = ContextVar("patient_feedback_admin_request", default=None)


LINK_ROW = '<div style="margin-bottom:.5rem">{}<br><code style="user-select:all;word-break:break-all">{}</code></div>'


# ── Per-language text fields ──────────────────────────────────────────
def localized_form(model, localized: dict, required: tuple = ()):
    """
    A ModelForm that edits JSON text fields ({"en": ..., "kn": ...}) as one
    box per configured language, e.g. ``text__en`` and ``text__kn``.

    ``localized`` maps field name → (label, rows). Fields in ``required``
    need their English text.
    """
    attrs = {}
    for name, (label, rows) in localized.items():
        for code, meta in LANGUAGES.items():
            widget = (
                forms.Textarea(attrs={"rows": rows, "cols": 60}) if rows > 1 else forms.TextInput(attrs={"size": 60})
            )
            attrs[f"{name}__{code}"] = forms.CharField(
                label=f"{label} ({meta['name']})",
                required=name in required and code == DEFAULT_LANGUAGE,
                widget=widget,
            )

    def __init__(self, *args, **kwargs):
        forms.ModelForm.__init__(self, *args, **kwargs)
        for name in localized:
            current = getattr(self.instance, name, None) or {}
            for code in LANGUAGES:
                self.fields[f"{name}__{code}"].initial = current.get(code, "")

    def clean(self):
        cleaned = forms.ModelForm.clean(self)
        # Pack before model validation, which checks the English text.
        for name in localized:
            setattr(
                self.instance,
                name,
                {code: value for code in LANGUAGES if (value := (cleaned.get(f"{name}__{code}") or "").strip())},
            )
        return cleaned

    def _update_errors(self, errors):
        # Model validation reports the JSON field ("text"); show it on the English box.
        if hasattr(errors, "error_dict"):
            for name in localized:
                if name in errors.error_dict:
                    errors.error_dict[f"{name}__{DEFAULT_LANGUAGE}"] = errors.error_dict.pop(name)
        forms.ModelForm._update_errors(self, errors)

    attrs.update(__init__=__init__, clean=clean, _update_errors=_update_errors)
    meta = type("Meta", (), {"model": model, "exclude": (*localized, "external_id", "deleted")})
    attrs["Meta"] = meta
    return type(f"Localized{model.__name__}Form", (forms.ModelForm,), attrs)


def language_fields(*names):
    return tuple(f"{name}__{code}" for name in names for code in LANGUAGES)


QuestionForm = localized_form(
    FeedbackQuestion,
    {"text": (_("Question"), 2), "short_text": (_("Review label"), 1), "hint": (_("Hint"), 1)},
    required=("text",),
)
QuestionInlineForm = localized_form(FeedbackQuestion, {"text": (_("Question"), 2)}, required=("text",))
FeedbackFormForm = localized_form(
    FeedbackForm, {"title": (_("Title"), 1), "description": (_("Description"), 1)}, required=("title",)
)


class QuestionInline(admin.TabularInline):
    model = FeedbackQuestion
    form = QuestionInlineForm
    fields = ("order", "key", "type", *language_fields("text"), "audience", "required", "is_active")
    extra = 0
    show_change_link = True
    ordering = ("order", "id")


@admin.register(FeedbackForm)
class FeedbackFormAdmin(admin.ModelAdmin):
    form = FeedbackFormForm
    list_display = ("form_title", "code", "patient_type", "facility", "is_active", "question_count", "order")
    list_filter = ("patient_type", "is_active")
    search_fields = ("code", "title", "facility__name")
    raw_id_fields = ("facility",)
    inlines = (QuestionInline,)
    fieldsets = (
        (None, {"fields": ("code", "patient_type", *language_fields("title", "description"))}),
        (_("Where"), {"fields": ("facility", "is_active", "order")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("facility")
            .annotate(_questions=Count("questions", filter=Q(questions__deleted=False, questions__is_active=True)))
        )

    @admin.display(description=_("Title"), ordering="code")
    def form_title(self, obj):
        return localize(obj.title, DEFAULT_LANGUAGE)

    @admin.display(description=_("Active questions"), ordering="_questions")
    def question_count(self, obj):
        return obj._questions


@admin.register(FeedbackQuestion)
class FeedbackQuestionAdmin(admin.ModelAdmin):
    form = QuestionForm
    list_display = ("question_text", "key", "type", "form", "order", "audience", "is_active")
    list_filter = ("type", "audience", "is_active", "form")
    search_fields = ("key", "text", "form__code")
    list_select_related = ("form",)
    raw_id_fields = ("form",)
    fieldsets = (
        (None, {"fields": ("form", "key", "order", "type", *language_fields("text", "short_text", "hint"))}),
        (
            _("Answers"),
            {"fields": ("options", "allow_no_comment", "allow_comment", "required", "audience", "is_active")},
        ),
    )

    @admin.display(description=_("Question"))
    def question_text(self, obj):
        return localize(obj.text, DEFAULT_LANGUAGE)


@admin.register(FeedbackKiosk)
class FeedbackKioskAdmin(admin.ModelAdmin):
    list_display = ("name", "facility", "is_active", "scan_mode", "last_seen_at")
    list_filter = ("is_active", "scan_mode", "default_language")
    search_fields = ("name", "facility__name", "external_id")
    raw_id_fields = ("facility", "patient_identifier_config")
    filter_horizontal = ("forms",)
    readonly_fields = ("external_id", "kiosk_link", "last_seen_at", "created_date", "modified_date")
    actions = ("regenerate_access_keys", "activate", "deactivate")
    fieldsets = (
        (None, {"fields": ("name", "facility", "is_active", "kiosk_link")}),
        (_("Screen"), {"fields": ("forms", "default_language", "scan_mode", "show_keypad")}),
        (_("Recording the patient"), {"fields": ("patient_identifier_config", "require_registered_uhid")}),
        (_("Info"), {"fields": ("external_id", "last_seen_at", "created_date", "modified_date")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("facility")

    def changeform_view(self, request, *args, **kwargs):
        token = _current_request.set(request)
        try:
            return super().changeform_view(request, *args, **kwargs)
        finally:
            _current_request.reset(token)

    @admin.display(description=_("Kiosk links"))
    def kiosk_link(self, obj):
        if not obj or not obj.pk:
            return _("Save the kiosk to get its link.")
        request = _current_request.get()

        def link(path):
            return f"{request.build_absolute_uri(path) if request else path}?key={obj.access_key}"

        start = reverse("patient_feedback:start", kwargs={"facility_id": obj.facility.external_id})
        rows = [(_("Patient chooses the form"), link(start))]
        for form in forms_for_kiosk(obj):
            path = reverse(
                "patient_feedback:identify", kwargs={"facility_id": obj.facility.external_id, "form": form.code}
            )
            rows.append((_("Only “%(title)s”") % {"title": localize(form.title, DEFAULT_LANGUAGE)}, link(path)))
        return format_html(
            "{}<small>Open one of these once on the kiosk screen; a form link keeps the screen on that form. "
            "They are secret: anyone with one can submit feedback for this kiosk. "
            "Use “Regenerate access key” to revoke them.</small>",
            format_html_join(
                "",
                LINK_ROW,
                rows,
            ),
        )

    @admin.action(description=_("Regenerate access key (logs the kiosk screen out)"))
    def regenerate_access_keys(self, request, queryset):
        for kiosk in queryset:
            kiosk.regenerate_access_key()
        self.message_user(request, _("New keys generated. Open the new kiosk link on each screen."), messages.WARNING)

    @admin.action(description=_("Switch on"))
    def activate(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description=_("Switch off"))
    def deactivate(self, request, queryset):
        queryset.update(is_active=False)


# ── Submissions ───────────────────────────────────────────────────────
def _csv_safe(value):
    """Stop spreadsheet apps from treating free text as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class _Echo:
    def write(self, value):
        return value


BASE_COLUMNS = (
    "reference_number",
    "submitted_at",
    "facility_name",
    "kiosk_name",
    "form_code",
    "patient_type",
    "identification_method",
    "uhid",
    "patient_external_id",
    "encounter_external_id",
    "language",
    "average_rating",
)


@admin.register(FeedbackSubmission)
class FeedbackSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "reference_number",
        "facility_name",
        "form_code",
        "patient_type",
        "identification_method",
        "average_rating",
        "submitted_at",
    )
    list_filter = ("patient_type", "form_code", "identification_method", "language")
    search_fields = ("reference_number", "uhid", "facility_name", "kiosk_name")
    date_hierarchy = "submitted_at"
    actions = ("export_csv",)
    fieldsets = (
        (None, {"fields": ("reference_number", "submitted_at", "started_at", "language")}),
        (_("Where"), {"fields": ("facility_name", "facility_external_id", "kiosk_name", "kiosk_external_id")}),
        (_("Form"), {"fields": ("form_title", "form_code", "patient_type", "form_external_id")}),
        (
            _("Who"),
            {"fields": ("identification_method", "uhid", "patient_external_id", "encounter_external_id")},
        ),
        (_("Answers"), {"fields": ("answers_table", "average_rating")}),
    )

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields] + ["answers_table"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Answers"))
    def answers_table(self, obj):
        rows = []
        for answer in obj.answers or []:
            display = answer.get("display") or "—"
            if answer.get("comment"):
                display = f"{display} — {answer['comment']}"
            rows.append((answer.get("question", answer.get("key")), display))
        return format_html(
            "<table>{}</table>", format_html_join("", "<tr><td>{}</td><td><strong>{}</strong></td></tr>", rows)
        )

    @admin.action(description=_("Export selected as CSV"))
    def export_csv(self, request, queryset):
        # One column per question key; OP and IP forms ask different questions,
        # so the columns are the union over the selection, in order of first use.
        queryset = queryset.order_by("submitted_at")
        keys = []
        for answers in queryset.values_list("answers", flat=True).iterator():
            for answer in answers or []:
                for column in (answer["key"], f"{answer['key']}__comment") if "comment" in answer else (answer["key"],):
                    if column not in keys:
                        keys.append(column)

        def rows():
            yield [*BASE_COLUMNS, *keys]
            for item in queryset.iterator():
                values = {}
                for answer in item.answers or []:
                    values[answer["key"]] = answer.get("display", "")
                    if "comment" in answer:
                        values[f"{answer['key']}__comment"] = answer.get("comment", "")
                base = [getattr(item, column) for column in BASE_COLUMNS]
                base[1] = timezone.localtime(item.submitted_at).isoformat()
                yield [*base, *[values.get(key, "") for key in keys]]

        writer = csv.writer(_Echo())
        response = StreamingHttpResponse(
            (writer.writerow([_csv_safe(value) for value in row]) for row in rows()),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="patient-feedback-{timezone.localdate():%Y%m%d}.csv"'
        return response
