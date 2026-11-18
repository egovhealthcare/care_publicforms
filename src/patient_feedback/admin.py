import csv
from contextvars import ContextVar

from care.facility.models import Facility
from django import forms
from django.contrib import admin
from django.db.models import Count, OuterRef, Q, Subquery
from django.http import StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from patient_feedback.i18n import BASE_LANGUAGE, admin_languages, localize
from patient_feedback.models import FeedbackForm, FeedbackQuestion, FeedbackSubmission
from patient_feedback.questionnaire import comment_key, display_answer, form_for_submission

# The admin's readonly-field callables only receive the object; this lets the
# page link use the host the admin is being served from.
_current_request: ContextVar = ContextVar("patient_feedback_admin_request", default=None)


# ── Per-language text fields ──────────────────────────────────────────
def localized_form(model, localized: dict, required: tuple = ()):
    """
    A ModelForm that edits JSON text fields ({"en": ..., "kn": ...}) as one
    box per configured language, e.g. ``text__en`` and ``text__kn``.

    ``localized`` maps field name → (label, rows). Fields in ``required``
    need their English text. There is a box for English and each offered
    language; text in other languages is kept as it is.
    """
    codes = admin_languages()
    attrs = {}
    for name, (label, rows) in localized.items():
        for code, meta in codes.items():
            widget = (
                forms.Textarea(attrs={"rows": rows, "cols": 60}) if rows > 1 else forms.TextInput(attrs={"size": 60})
            )
            attrs[f"{name}__{code}"] = forms.CharField(
                label=f"{label} ({meta['name']})",
                required=name in required and code == BASE_LANGUAGE,
                widget=widget,
            )

    def __init__(self, *args, **kwargs):
        forms.ModelForm.__init__(self, *args, **kwargs)
        for name in localized:
            current = getattr(self.instance, name, None) or {}
            for code in codes:
                self.fields[f"{name}__{code}"].initial = current.get(code, "")

    def clean(self):
        cleaned = forms.ModelForm.clean(self)
        # Pack before model validation, which checks the English text.
        for name in localized:
            text = dict(getattr(self.instance, name, None) or {})
            for code in codes:
                if value := (cleaned.get(f"{name}__{code}") or "").strip():
                    text[code] = value
                else:
                    text.pop(code, None)
            setattr(self.instance, name, text)
        return cleaned

    def _update_errors(self, errors):
        # Model validation reports the JSON field ("text"); show it on the English box.
        if hasattr(errors, "error_dict"):
            for name in localized:
                if name in errors.error_dict:
                    errors.error_dict[f"{name}__{BASE_LANGUAGE}"] = errors.error_dict.pop(name)
        forms.ModelForm._update_errors(self, errors)

    attrs.update(__init__=__init__, clean=clean, _update_errors=_update_errors)
    attrs["Meta"] = type("Meta", (), {"model": model, "exclude": tuple(localized)})
    return type(f"Localized{model.__name__}Form", (forms.ModelForm,), attrs)


def language_fields(*names):
    return tuple(f"{name}__{code}" for name in names for code in admin_languages())


QuestionForm = localized_form(
    FeedbackQuestion,
    {"text": (_("Question"), 2), "short_text": (_("Review label"), 1), "hint": (_("Hint"), 1)},
    required=("text",),
)
QuestionInlineForm = localized_form(FeedbackQuestion, {"text": (_("Question"), 2)}, required=("text",))
FeedbackFormForm = localized_form(
    FeedbackForm, {"title": (_("Title"), 1), "description": (_("Description"), 1)}, required=("title",)
)


# ── Forms & questions ─────────────────────────────────────────────────
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
    readonly_fields = ("page_link",)
    inlines = (QuestionInline,)
    fieldsets = (
        (None, {"fields": ("code", "patient_type", *language_fields("title", "description"))}),
        (_("Where"), {"fields": ("facility", "is_active", "order", "page_link")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("facility")
            .annotate(_questions=Count("questions", filter=Q(questions__is_active=True)))
        )

    def changeform_view(self, request, *args, **kwargs):
        token = _current_request.set(request)
        try:
            response = super().changeform_view(request, *args, **kwargs)
            # Render now: a TemplateResponse renders lazily, after the reset below.
            if hasattr(response, "render") and not response.is_rendered:
                response.render()
            return response
        finally:
            _current_request.reset(token)

    @admin.display(description=_("Title"), ordering="code")
    def form_title(self, obj):
        return localize(obj.title, BASE_LANGUAGE)

    @admin.display(description=_("Active questions"), ordering="_questions")
    def question_count(self, obj):
        return obj._questions

    @admin.display(description=_("Page"))
    def page_link(self, obj):
        if not obj or not obj.pk:
            return _("Save the form to see its link.")
        if obj.facility is None:
            path = reverse(
                "patient_feedback:form",
                kwargs={"facility_id": "00000000-0000-0000-0000-000000000000", "form": obj.code},
            ).replace("00000000-0000-0000-0000-000000000000", "<facility-id>")
            return format_html(
                "<code>{}</code><br><small>{}</small>",
                path,
                _("Open it on a screen with a facility's id; the screen then stays on this form."),
            )
        request = _current_request.get()
        path = reverse("patient_feedback:form", kwargs={"facility_id": obj.facility.external_id, "form": obj.code})
        url = request.build_absolute_uri(path) if request else path
        return format_html(
            '<code style="user-select:all;word-break:break-all">{}</code><br><small>{}</small>',
            url,
            _("Open it on a screen to keep that screen on this form. It is public: no login is needed."),
        )


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
        return localize(obj.text, BASE_LANGUAGE)


# ── Submissions ───────────────────────────────────────────────────────
def _csv_safe(value):
    """Stop spreadsheet apps from treating free text as a formula (CSV injection)."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class _Echo:
    def write(self, value):
        return value


CSV_COLUMNS = ("reference_number", "submitted_at", "facility", "form_code", "patient_type", "language", "uhid")


def with_facility_name(queryset):
    return queryset.annotate(
        facility_name=Subquery(Facility.objects.filter(external_id=OuterRef("facility_external_id")).values("name")[:1])
    )


@admin.register(FeedbackSubmission)
class FeedbackSubmissionAdmin(admin.ModelAdmin):
    list_display = ("reference_number", "facility", "form_code", "patient_type", "uhid", "submitted_at")
    list_filter = ("patient_type", "form_code", "language")
    search_fields = ("reference_number", "uhid")
    date_hierarchy = "submitted_at"
    actions = ("export_csv",)
    fields = (
        "reference_number",
        "submitted_at",
        "facility",
        "form_code",
        "patient_type",
        "language",
        "uhid",
        "answers_table",
    )
    readonly_fields = fields

    def get_queryset(self, request):
        return with_facility_name(super().get_queryset(request))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Facility"))
    def facility(self, obj):
        return obj.facility_name or obj.facility_external_id

    @admin.display(description=_("Answers"))
    def answers_table(self, obj):
        # Labels come from the form as it is now; keys no longer on it are shown as stored.
        form = form_for_submission(obj.facility_external_id, obj.form_code)
        questions = {q.key: q for q in form.questions.all()} if form else {}
        answers = dict(obj.answers or {})
        rows = []
        for question in sorted(questions.values(), key=lambda q: (q.order, q.id)):
            if question.key not in answers:
                continue
            value = display_answer(question, answers.pop(question.key))
            if comment := answers.pop(comment_key(question), ""):
                value = f"{value} — {comment}"
            rows.append((localize(question.text, BASE_LANGUAGE), value))
        rows.extend((key, value) for key, value in answers.items())
        return format_html(
            "<table>{}</table>", format_html_join("", "<tr><td>{}</td><td><strong>{}</strong></td></tr>", rows)
        )

    @admin.action(description=_("Export selected as CSV"))
    def export_csv(self, request, queryset):
        # One column per answer key; OP and IP forms ask different questions,
        # so the columns are the union over the selection, in the forms'
        # question order (keys no longer on a form go last).
        queryset = with_facility_name(queryset.order_by("submitted_at"))
        found = set()
        for answers in queryset.values_list("answers", flat=True).iterator():
            found.update(answers or {})
        order = {}
        questions = FeedbackQuestion.objects.filter(form__code__in=queryset.values("form_code"))
        for key in questions.order_by("form__order", "form_id", "order", "id").values_list("key", flat=True):
            order.setdefault(key, len(order))
        keys = sorted(found, key=lambda k: (order.get(k.removesuffix("__comment"), len(order)), k))

        def rows():
            yield [*CSV_COLUMNS, *keys]
            for item in queryset.iterator():
                base = [
                    item.reference_number,
                    timezone.localtime(item.submitted_at).isoformat(),
                    item.facility_name or item.facility_external_id,
                    item.form_code,
                    item.patient_type,
                    item.language,
                    item.uhid,
                ]
                answers = item.answers or {}
                yield [*base, *(answers.get(key, "") for key in keys)]

        writer = csv.writer(_Echo())
        response = StreamingHttpResponse(
            (writer.writerow([_csv_safe(value) for value in row]) for row in rows()),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="patient-feedback-{timezone.localdate():%Y%m%d}.csv"'
        return response
