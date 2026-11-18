import csv
from contextvars import ContextVar

from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from patient_feedback.models import FeedbackKiosk, FeedbackResponse
from patient_feedback.questionnaire import RATING_QUESTIONS, SCALE

# The admin's readonly-field callables only receive the object; this lets the
# kiosk link use the host the admin is being served from.
_current_request: ContextVar = ContextVar("patient_feedback_admin_request", default=None)


@admin.register(FeedbackKiosk)
class FeedbackKioskAdmin(admin.ModelAdmin):
    list_display = ("name", "facility", "is_active", "scan_mode", "last_seen_at", "response_count")
    list_filter = ("is_active", "scan_mode", "default_language")
    search_fields = ("name", "facility__name", "external_id")
    raw_id_fields = ("facility", "patient_identifier_config")
    readonly_fields = ("external_id", "kiosk_link", "last_seen_at", "created_date", "modified_date")
    actions = ("regenerate_access_keys", "activate", "deactivate")
    fieldsets = (
        (None, {"fields": ("name", "facility", "is_active", "kiosk_link")}),
        (_("Screen"), {"fields": ("default_language", "scan_mode", "show_keypad", "clinics")}),
        (_("Linking responses to patients"), {"fields": ("patient_identifier_config", "require_registered_uhid")}),
        (_("Info"), {"fields": ("external_id", "last_seen_at", "created_date", "modified_date")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("facility")
            .annotate(_responses=Count("responses", filter=Q(responses__deleted=False)))
        )

    def changeform_view(self, request, *args, **kwargs):
        token = _current_request.set(request)
        try:
            return super().changeform_view(request, *args, **kwargs)
        finally:
            _current_request.reset(token)

    @admin.display(description=_("Responses"), ordering="_responses")
    def response_count(self, obj):
        return getattr(obj, "_responses", None)

    @admin.display(description=_("Kiosk link"))
    def kiosk_link(self, obj):
        if not obj or not obj.pk:
            return _("Save the kiosk to get its link.")
        path = reverse("patient_feedback:start", kwargs={"kiosk_id": obj.external_id})
        request = _current_request.get()
        url = f"{request.build_absolute_uri(path) if request else path}?key={obj.access_key}"
        return format_html(
            '<code style="user-select:all;word-break:break-all">{}</code><br>'
            "<small>Open this once on the kiosk screen. It is a secret: anyone with it can submit "
            "feedback for this kiosk. Use “Regenerate access key” to revoke it.</small>",
            url,
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


def _csv_safe(value):
    """Stop spreadsheet apps from treating free text as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class _Echo:
    def write(self, value):
        return value


@admin.register(FeedbackResponse)
class FeedbackResponseAdmin(admin.ModelAdmin):
    list_display = (
        "reference_number",
        "facility",
        "kiosk",
        "identification_method",
        "average_rating",
        "would_return",
        "language",
        "submitted_at",
    )
    list_filter = ("identification_method", "language", "would_return", "questionnaire_version")
    search_fields = ("reference_number", "uhid", "facility__name", "kiosk__name")
    date_hierarchy = "submitted_at"
    actions = ("export_csv",)
    fieldsets = (
        (None, {"fields": ("reference_number", "facility", "kiosk", "submitted_at", "started_at", "language")}),
        (_("Who"), {"fields": ("identification_method", "uhid", "patient", "encounter", "clinic", "age_group", "sex")}),
        (_("Ratings"), {"fields": ("ratings_table", "average_rating", "questionnaire_version")}),
        (
            _("In their own words"),
            {
                "fields": (
                    "would_return",
                    "would_return_reason",
                    "improvement",
                    "reason_for_choosing",
                    "suggestions",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("facility", "kiosk", "patient", "encounter")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields] + ["ratings_table"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Ratings"))
    def ratings_table(self, obj):
        rows = []
        for question in RATING_QUESTIONS:
            value = obj.ratings.get(question.key)
            rows.append((question.short["en"], SCALE[value]["en"] if value in SCALE else "—"))
        return format_html(
            "<table>{}</table>", format_html_join("", "<tr><td>{}</td><td><strong>{}</strong></td></tr>", rows)
        )

    @admin.action(description=_("Export selected as CSV"))
    def export_csv(self, request, queryset):
        keys = [question.key for question in RATING_QUESTIONS]
        header = [
            "reference_number",
            "submitted_at",
            "facility",
            "kiosk",
            "identification_method",
            "uhid",
            "patient_id",
            "encounter_id",
            "clinic",
            "age_group",
            "sex",
            "language",
            *keys,
            "average_rating",
            "would_return",
            "would_return_reason",
            "improvement",
            "reason_for_choosing",
            "suggestions",
            "questionnaire_version",
        ]

        def rows():
            yield header
            for item in queryset.select_related("facility", "kiosk", "patient", "encounter").iterator():
                yield [
                    item.reference_number,
                    timezone.localtime(item.submitted_at).isoformat(),
                    item.facility.name,
                    item.kiosk.name,
                    item.identification_method,
                    item.uhid,
                    item.patient.external_id if item.patient else "",
                    item.encounter.external_id if item.encounter else "",
                    item.clinic,
                    item.age_group,
                    item.sex,
                    item.language,
                    *[item.ratings.get(key, "") for key in keys],
                    item.average_rating if item.average_rating is not None else "",
                    {True: "yes", False: "no"}.get(item.would_return, ""),
                    item.would_return_reason,
                    item.improvement,
                    item.reason_for_choosing,
                    item.suggestions,
                    item.questionnaire_version,
                ]

        writer = csv.writer(_Echo())
        response = StreamingHttpResponse(
            (writer.writerow([_csv_safe(value) for value in row]) for row in rows()),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="patient-feedback-{timezone.localdate():%Y%m%d}.csv"'
        return response
