import csv
import json
from contextvars import ContextVar
from functools import lru_cache

from care.facility.models import Facility
from django import forms
from django.contrib import admin
from django.db.models import OuterRef, Subquery
from django.forms.fields import InvalidJSONInput
from django.http import StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from public_forms.access import MANAGE_FORMS, VIEW_FEEDBACK, facility_ids
from public_forms.admin_site import site
from public_forms.i18n import BASE_LANGUAGE, admin_languages, localize
from public_forms.models import FeedbackForm, FeedbackSubmission
from public_forms.questions import FIELDS, parse_questions, with_steps
from public_forms.text_rules import (
    MAX_DESCRIPTION_LENGTH,
    MAX_OPTION_LENGTH,
    MAX_OPTION_VALUE_LENGTH,
    MAX_QUESTION_LENGTH,
    MAX_SHORT_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
    spaced,
    validate_typed_text,
)

# The screens are registered on the plugin's own admin site (admin_site.py),
# not on Django's /admin/.

# The admin's readonly-field callables only receive the object; this lets the
# page link use the host the admin is being served from.
_current_request: ContextVar = ContextVar("public_forms_admin_request", default=None)


# ── Per-language text fields ──────────────────────────────────────────
def localized_form(model, localized: dict, required: tuple = ()):
    """
    A ModelForm that edits JSON text fields ({"en": ..., "<code>": ...}) as
    one box per configured language: ``text__en``, ``text__<code>``.

    ``localized`` maps field name → (label, rows). Fields in ``required``
    need their English text. There is a box for English and each offered
    language; text in other languages is kept as it is. Each box follows
    text_rules: no blocked characters, and the field's length limit.
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
                max_length=TEXT_LIMITS.get(name),
                validators=[validate_typed_text],
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
        # Model validation reports the JSON field ("text"); show it on the English box,
        # unless that box already has its own error (e.g. a blocked character).
        if hasattr(errors, "error_dict"):
            for name in localized:
                if name in errors.error_dict:
                    moved = errors.error_dict.pop(name)
                    if f"{name}__{BASE_LANGUAGE}" not in self._errors:
                        errors.error_dict[f"{name}__{BASE_LANGUAGE}"] = moved
        forms.ModelForm._update_errors(self, errors)

    attrs.update(__init__=__init__, clean=clean, _update_errors=_update_errors)
    attrs["Meta"] = type("Meta", (), {"model": model, "exclude": tuple(localized)})
    return type(f"Localized{model.__name__}Form", (forms.ModelForm,), attrs)


def language_fields(*names):
    return tuple(f"{name}__{code}" for name in names for code in admin_languages())


class QuestionsJSONField(forms.JSONField):
    """The questions (or step titles) as indented JSON in a large box."""

    def __init__(self, *args, empty=None, **kwargs):
        self.empty = [] if empty is None else empty
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, InvalidJSONInput):
            return value
        return json.dumps(value if value is not None else self.empty, indent=2, ensure_ascii=False)


QUESTIONS_HELP = format_html(
    "{}<br><code>{}</code><ul>{}</ul>{}",
    _(
        "A list of questions in the order they are asked. Fields with their default can be left out. "
        "Submissions keep their own copy of each question, so editing, reordering or removing a question "
        "doesn't change feedback already given; but give a question with a new meaning a new key."
    ),
    '[{"key": "clinic", "type": "choice", "required": true, "text": {"en": "Clinic visited"}, '
    '"options": [{"value": "ent", "en": "ENT"}]}, …]',
    format_html_join(
        "",
        "<li><code>{}</code>{}: {}</li>",
        (
            (name, f" (default {json.dumps(default)})" if default is not None else "", text)
            for name, (default, text) in FIELDS.items()
        ),
    ),
    _(
        "No text can contain %(characters)s. Limits per language: text and hint %(question)s characters, "
        "short_text %(short)s, each option's label %(option)s; an option's value %(value)s."
    )
    % {
        "characters": spaced(),
        "question": MAX_QUESTION_LENGTH,
        "short": MAX_SHORT_TEXT_LENGTH,
        "option": MAX_OPTION_LENGTH,
        "value": MAX_OPTION_VALUE_LENGTH,
    },
)


STEPS_HELP = format_html(
    "{}<br><code>{}</code>",
    _(
        "Optional: a heading for a step of choice, date or text questions, by its number, per language. "
        "A step without one gets a default (“A few quick details” before the ratings, “In your own words” "
        "after them). Rating steps take none: each card shows its question."
    ),
    '{"1": {"title": {"en": "About your visit"}, "lead": {"en": "Two quick questions."}}}',
)

TEXT_FIELDS = {"title": (_("Title"), 1), "description": (_("Description"), 1)}
TEXT_LIMITS = {"title": MAX_TITLE_LENGTH, "description": MAX_DESCRIPTION_LENGTH}


def feedback_form_form() -> type:
    """The form admin's form: a box per admin language for the title and description, and the questions JSON."""
    return _feedback_form_form(tuple(admin_languages()))


@lru_cache(maxsize=8)
def _feedback_form_form(codes: tuple) -> type:
    # Built per set of languages, so the boxes follow the LANGUAGES setting.
    return type(
        "FeedbackFormForm",
        (localized_form(FeedbackForm, TEXT_FIELDS, required=("title",)),),
        {
            "questions": QuestionsJSONField(
                required=False,
                help_text=QUESTIONS_HELP,
                widget=forms.Textarea(
                    attrs={
                        "rows": 32,
                        "cols": 110,
                        "spellcheck": "false",
                        "style": "font-family:ui-monospace,Menlo,monospace;font-size:12px",
                    }
                ),
            ),
            "steps": QuestionsJSONField(
                required=False,
                empty={},
                label=_("Step titles"),
                help_text=STEPS_HELP,
                widget=forms.Textarea(
                    attrs={
                        "rows": 8,
                        "cols": 110,
                        "spellcheck": "false",
                        "style": "font-family:ui-monospace,Menlo,monospace;font-size:12px",
                    }
                ),
            ),
            # Every question is saved with its step as a number, so the JSON says where each is asked.
            "clean_questions": lambda self: with_steps(self.cleaned_data.get("questions") or []),
            "clean_steps": lambda self: self.cleaned_data.get("steps") or {},
        },
    )


# ── Forms ─────────────────────────────────────────────────────────────
@admin.register(FeedbackForm, site=site)
class FeedbackFormAdmin(admin.ModelAdmin):
    list_display = ("form_title", "code", "patient_type", "facility", "is_active", "question_count", "order")
    list_filter = ("patient_type", "is_active")
    search_fields = ("code", "title", "facility_external_id")
    readonly_fields = ("facility", "page_link")

    def get_fieldsets(self, request, obj=None):
        return (
            (None, {"fields": ("code", "patient_type", *language_fields(*TEXT_FIELDS))}),
            (_("Questions"), {"fields": ("questions", "steps")}),
            (_("Where"), {"fields": ("facility_external_id", "facility", "is_active", "order", "page_link")}),
        )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **{"form": feedback_form_form(), **kwargs})
        managed = facility_ids(request.user, MANAGE_FORMS)
        if managed is None:
            return form
        allowed = set(managed)

        class OwnFacilitiesForm(form):
            def clean_facility_external_id(self):
                value = self.cleaned_data.get("facility_external_id")
                if value is not None and value not in allowed:
                    raise forms.ValidationError(_("You can't set up forms for this facility."))
                return value

        return OwnFacilitiesForm

    def get_queryset(self, request):
        # The facilities whose feedback the user sees or whose forms they set up (access.py).
        queryset = super().get_queryset(request)
        reachable = facility_ids(request.user, VIEW_FEEDBACK, MANAGE_FORMS)
        if reachable is not None:
            queryset = queryset.filter(facility_external_id__in=reachable)
        # No foreign key: the facility's name is looked up by its id.
        return with_facility_name(queryset)

    def manages(self, request, obj) -> bool:
        """Whether the user sets up forms for ``obj``'s facility; any form is shown read-only otherwise."""
        if obj is None:
            return True
        managed = facility_ids(request.user, MANAGE_FORMS)
        return managed is None or managed.filter(external_id=obj.facility_external_id).exists()

    def has_add_permission(self, request):
        managed = facility_ids(request.user, MANAGE_FORMS)
        return super().has_add_permission(request) and (managed is None or managed.exists())

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self.manages(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self.manages(request, obj)

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

    @admin.display(description=_("Facility"))
    def facility(self, obj):
        if not obj or not obj.facility_external_id:
            return None  # a new form: the admin shows its empty value
        return getattr(obj, "facility_name", None) or _("Unknown facility")

    @admin.display(description=_("Active questions"))
    def question_count(self, obj):
        return sum(1 for question in parse_questions(obj.questions) if question.active)

    @admin.display(description=_("Page"))
    def page_link(self, obj):
        if not obj or not obj.pk:
            return _("Save the form to see its link.")
        request = _current_request.get()
        path = reverse("public_forms:form", kwargs={"facility_id": obj.facility_external_id, "form": obj.code})
        url = request.build_absolute_uri(path) if request else path
        return format_html(
            '<code style="user-select:all;word-break:break-all">{}</code><br><small>{}</small>',
            url,
            _("Open it on a screen to keep that screen on this form. It is public: no login is needed."),
        )


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


def ordered_keys(keys, order: list[str]) -> list[str]:
    """``keys`` in ``order`` (a "<key>__comment" right after its key); keys not in it last."""
    position = {key: index for index, key in enumerate(order)}
    return sorted(keys, key=lambda k: (position.get(k.removesuffix("__comment"), len(order)), k))


def csv_cell(answers: dict, column: str):
    key, _sep, part = column.partition("__")
    entry = answers.get(key)
    if not isinstance(entry, dict):
        return entry if entry is not None and not part else ""
    return entry.get("comment", "") if part == "comment" else entry.get("value", "")


def with_facility_name(queryset):
    return queryset.annotate(
        facility_name=Subquery(Facility.objects.filter(external_id=OuterRef("facility_external_id")).values("name")[:1])
    )


@admin.register(FeedbackSubmission, site=site)
class FeedbackSubmissionAdmin(admin.ModelAdmin):
    list_display = ("reference_number", "facility", "form_code", "patient_type", "uhid", "submitted_at")
    # Only the forms of the submissions the user can see, not every facility's.
    list_filter = ("form__patient_type", ("form", admin.RelatedOnlyFieldListFilter), "language")
    search_fields = ("reference_number", "uhid")
    date_hierarchy = "submitted_at"
    actions = ("export_csv",)
    fields = (
        "reference_number",
        "submitted_at",
        "facility",
        "form",
        "patient_type",
        "language",
        "uhid",
        "answers_table",
    )
    readonly_fields = fields

    def get_queryset(self, request):
        # Only facilities whose feedback the user may see (access.py). The
        # detail pages, history and CSV export all start from this.
        queryset = super().get_queryset(request)
        visible = facility_ids(request.user, VIEW_FEEDBACK)
        if visible is not None:
            queryset = queryset.filter(facility_external_id__in=visible)
        return with_facility_name(queryset).select_related("form")

    @admin.display(description=_("Form"), ordering="form__code")
    def form_code(self, obj):
        return obj.form.code

    @admin.display(description=_("Patient type"), ordering="form__patient_type")
    def patient_type(self, obj):
        return obj.form.get_patient_type_display()

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
        # Each answer carries its question as asked; its form's current order is used for display.
        answers = obj.answers or {}
        rows = []
        order = [question.key for question in parse_questions(obj.form.questions)]
        for key in ordered_keys(answers, order):
            entry = answers[key] if isinstance(answers[key], dict) else {"value": answers[key]}
            shown = entry.get("answer", entry.get("value"))
            if entry.get("type") == "rating" and "answer" in entry:
                shown = f"{entry.get('value')} · {entry['answer']}"
            elif isinstance(shown, bool):
                shown = _("Yes") if shown else _("No")
            if entry.get("comment"):
                shown = f"{shown} ({entry['comment']})"
            rows.append((entry.get("question") or key, shown))
        return format_html(
            "<table>{}</table>", format_html_join("", "<tr><td>{}</td><td><strong>{}</strong></td></tr>", rows)
        )

    @admin.action(description=_("Export selected as CSV"))
    def export_csv(self, request, queryset):
        # One column per answer key; OP and IP forms ask different questions,
        # so the columns are the union over the selection, in the forms'
        # question order (keys no longer on a form go last).
        # Each cell is the stored value (ratings 0 to 5, choice codes, yes/no); a
        # "Why?" gets its own <key>__comment column.
        queryset = with_facility_name(queryset.order_by("submitted_at")).select_related("form")
        found = set()
        for answers in queryset.values_list("answers", flat=True).iterator():
            for key, entry in (answers or {}).items():
                found.add(key)
                if isinstance(entry, dict) and entry.get("comment"):
                    found.add(f"{key}__comment")
        order = []
        forms = FeedbackForm.objects.filter(pk__in=queryset.values("form")).order_by("order", "id")
        for questions in forms.values_list("questions", flat=True):
            order += [question.key for question in parse_questions(questions)]
        keys = ordered_keys(found, list(dict.fromkeys(order)))

        def rows():
            yield [*CSV_COLUMNS, *keys]
            for item in queryset.iterator():
                base = [
                    item.reference_number,
                    timezone.localtime(item.submitted_at).isoformat(),
                    item.facility_name or item.facility_external_id,
                    item.form.code,
                    item.form.patient_type,
                    item.language,
                    item.uhid,
                ]
                yield [*base, *(csv_cell(item.answers or {}, key) for key in keys)]

        writer = csv.writer(_Echo())
        response = StreamingHttpResponse(
            (writer.writerow([_csv_safe(value) for value in row]) for row in rows()),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="public-forms-{timezone.localdate():%Y%m%d}.csv"'
        return response
