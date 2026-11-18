"""
Public, server-rendered feedback pages: no login, kiosk key, session or
cookies. Anyone in the hospital can open them.

  /facility/<id>/patient_feedback/            form chooser (or straight to the only form)
  /facility/<id>/patient_feedback/<form>/     the whole questionnaire on one page; POST saves it
  /facility/<id>/patient_feedback/<form>/done/?ref=…   thank you + reference number

The questionnaire page holds every step (identify, details, ratings, open
questions, review) and both languages; kiosk.js moves between the steps in
the browser and the page is posted once at the end. Without JavaScript the
same page is one long form.

A screen can set its own options in the URL: ?lang=kn (starting language),
?scan=camera|scanner|off and ?keypad=0|1. A screen opened on a form's URL
stays on that form; one opened on the chooser returns to the chooser.
"""

import math

from care.facility.models import Facility
from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.core import is_ratelimited

from patient_feedback.i18n import DEFAULT_LANGUAGE, LANGUAGES, localize, normalize_language
from patient_feedback.models import FeedbackSubmission, QuestionType
from patient_feedback.questionnaire import (
    FormSpec,
    choice_labels,
    comment_key,
    forms_for_facility,
    rating_labels,
)
from patient_feedback.services import (
    collect_answers,
    create_submission,
    digits_of,
    parse_uhid,
    uhid_groups,
    uhid_length,
)
from patient_feedback.settings import plugin_settings

SCAN_MODES = ("camera", "scanner", "off")
SECONDS_PER_QUESTION = 12  # for "about N minutes"


class FeedbackPage(View):
    """Resolves the facility, its forms and the screen's URL options."""

    def dispatch(self, request, *args, **kwargs):
        self.facility = Facility.objects.filter(external_id=kwargs.pop("facility_id")).first()
        if self.facility is None:
            return self.render_empty("unknown_facility")
        self.forms = forms_for_facility(self.facility)
        if not self.forms:
            return self.render_empty("no_forms")
        self.options = self.screen_options(request)
        self.form = None
        if (code := kwargs.pop("form", None)) is not None:
            self.form = next((f for f in self.forms if f.code == code), None)
            if self.form is None:
                return HttpResponseRedirect(self.chooser_url())
        return super().dispatch(request, *args, **kwargs)

    # ── per-screen options from the URL ──────────────────────────────
    def screen_options(self, request) -> dict:
        params = request.GET
        options = {}
        if params.get("lang") in LANGUAGES:
            options["lang"] = params["lang"]
        if params.get("scan") in SCAN_MODES:
            options["scan"] = params["scan"]
        if params.get("keypad") in ("0", "1"):
            options["keypad"] = params["keypad"]
        return options

    @property
    def default_language(self) -> str:
        return self.options.get("lang") or normalize_language(plugin_settings.DEFAULT_LANGUAGE)

    @property
    def scan_mode(self) -> str:
        mode = self.options.get("scan") or plugin_settings.SCAN_MODE
        return mode if mode in SCAN_MODES else "camera"

    @property
    def show_keypad(self) -> bool:
        if "keypad" in self.options:
            return self.options["keypad"] == "1"
        return bool(plugin_settings.SHOW_KEYPAD)

    # ── URLs ─────────────────────────────────────────────────────────
    def _url(self, name, query=None, **kwargs) -> str:
        url = reverse(f"patient_feedback:{name}", kwargs={"facility_id": self.facility.external_id, **kwargs})
        query = {**self.options, **(query or {})}
        return f"{url}?{urlencode(query)}" if query else url

    def chooser_url(self) -> str:
        return self._url("start")

    def form_url(self, form, **query) -> str:
        return self._url("form", query, form=form.code)

    def home_url(self, came_from_chooser: bool) -> str:
        """Where the next patient starts: the chooser, or this form if the screen was opened on it."""
        if came_from_chooser and len(self.forms) > 1:
            return self.chooser_url()
        return self.form_url(self.form)

    # ── rendering ────────────────────────────────────────────────────
    def render_empty(self, reason: str):
        return render(self.request, "patient_feedback/empty.html", {"reason": reason}, status=404)

    def base_context(self, title) -> dict:
        lang = self.default_language
        return {
            "facility_name": self.facility.name,
            "title": title,
            "title_text": localize(title, lang) if isinstance(title, dict) else "",
            "lang": lang,
            "default_lang": lang,
            "languages": [
                {"code": code, "label": meta["toggle"], "name": meta["name"], "active": code == lang}
                for code, meta in LANGUAGES.items()
            ],
            "today": timezone.localdate(),
            "idle_timeout": int(plugin_settings.IDLE_TIMEOUT_SECONDS),
            "load_web_fonts": bool(plugin_settings.LOAD_WEB_FONTS),
        }


# ── Chooser ────────────────────────────────────────────────────────────
class StartView(FeedbackPage):
    def get(self, request):
        if len(self.forms) == 1:
            return HttpResponseRedirect(self.form_url(self.forms[0]))
        options = [
            {
                "title": form.title,
                "description": form.description,
                "patient_type": form.patient_type,
                "url": self.form_url(form, **{"from": "start"}),
            }
            for form in self.forms
        ]
        context = self.base_context(None)
        context.update(options=options, home_url=self.chooser_url(), idle_timeout=0)
        return render(request, "patient_feedback/choose.html", context)


# ── The questionnaire ──────────────────────────────────────────────────
@method_decorator(csrf_exempt, name="dispatch")  # public form with no session or cookies to protect
class FormView(FeedbackPage):
    def get(self, request, **kwargs):
        return self.render_form(came_from_chooser=request.GET.get("from") == "start")

    def post(self, request, **kwargs):
        came_from_chooser = request.POST.get("from") == "start"
        if not getattr(settings, "DISABLE_RATELIMIT", False) and is_ratelimited(
            request, group="patient_feedback.submit", key="ip", rate=plugin_settings.SUBMIT_RATE_LIMIT, increment=True
        ):
            return self.render_form(came_from_chooser, data=request.POST, banner="too_many", status=429)

        spec = FormSpec(self.form)
        raw_uhid = digits_of(request.POST.get("uhid"))
        uhid = parse_uhid(raw_uhid) if raw_uhid else ""
        answers, missing = collect_answers(spec, request.POST, identified=bool(uhid))
        if uhid is None:
            missing["uhid"] = "length"
        if missing:
            return self.render_form(came_from_chooser, data=request.POST, errors=missing, banner="error_summary")

        language = normalize_language(request.POST.get("language"), self.default_language)
        submission = create_submission(self.facility, self.form, language, uhid or "", answers)
        query = {"ref": submission.reference_number, **({"from": "start"} if came_from_chooser else {})}
        return HttpResponseRedirect(self._url("done", query, form=self.form.code))

    def render_form(self, came_from_chooser: bool, data=None, errors=None, banner=None, status=200):
        data = data or {}
        errors = errors or {}
        spec = FormSpec(self.form)
        uhid = digits_of(data.get("uhid"))[: uhid_length()]
        gaps, position = set(), 0
        for size in uhid_groups()[:-1]:
            position += size
            gaps.add(position)

        def field(question, index=None):
            item = {
                "key": question.key,
                "type": question.type,
                "text": question.text,
                "hint": question.hint,
                "label": question.short_text or question.text,
                "audience": question.audience,
                "required": question.required or question.type == QuestionType.RATING,
                "value": str(data.get(question.key, "")),
                "error": question.key in errors,
            }
            if question.type == QuestionType.RATING:
                item.update(
                    index=index,
                    number=index + 1,
                    options=[{"value": str(v), "label": label} for v, label in rating_labels(question).items()],
                )
            elif question.type == QuestionType.CHOICE:
                options = choice_labels(question)
                item["options"] = [{"value": code, "label": labels} for code, labels in options.items()]
                item["compact"] = all(len(localize(labels, DEFAULT_LANGUAGE)) <= 12 for labels in options.values())
            elif question.type == QuestionType.YES_NO:
                item.update(
                    allow_comment=question.allow_comment,
                    comment_key=comment_key(question),
                    comment=data.get(comment_key(question), ""),
                )
            return item

        ratings = [field(q, i) for i, q in enumerate(spec.ratings)]
        details = [field(q) for q in spec.details]
        open_questions = [field(q) for q in spec.open_questions]

        # After a failed submit, open the first step with a problem.
        start_step, start_card = "identify", 0
        if errors:
            if "uhid" in errors:
                start_step = "uhid"
            elif any(f["error"] for f in details):
                start_step = "details"
            elif any(r["error"] for r in ratings):
                start_step, start_card = "questions", next(r["index"] for r in ratings if r["error"])
            else:
                start_step = "comments"

        context = self.base_context(self.form.title)
        if data.get("language") in LANGUAGES:
            context["lang"] = data["language"]
        context.update(
            home_url=self.home_url(came_from_chooser),
            back_to_chooser=self.chooser_url() if came_from_chooser and len(self.forms) > 1 else None,
            came_from_chooser=came_from_chooser,
            step_number=2 if came_from_chooser and len(self.forms) > 1 else 1,
            details=details,
            ratings=ratings,
            open_questions=open_questions,
            open_questions_required=any(f["required"] for f in open_questions),
            rating_count=spec.rating_count_for_everyone,
            minutes=max(1, math.ceil(len(spec.questions) * SECONDS_PER_QUESTION / 60)),
            uhid=uhid,
            uhid_length=uhid_length(),
            uhid_cells=[{"digit": uhid[i] if i < len(uhid) else "", "gap": i in gaps} for i in range(uhid_length())],
            keypad=["1", "2", "3", "4", "5", "6", "7", "8", "9"],
            show_keypad=self.show_keypad,
            scan_mode=self.scan_mode,
            errors=errors,
            banner=banner,
            start_step=start_step,
            start_card=start_card,
        )
        return render(self.request, "patient_feedback/form.html", context, status=status)


# ── Thank you ──────────────────────────────────────────────────────────
class DoneView(FeedbackPage):
    def get(self, request, **kwargs):
        came_from_chooser = request.GET.get("from") == "start"
        home = self.home_url(came_from_chooser)
        reference = request.GET.get("ref", "")
        exists = FeedbackSubmission.objects.filter(
            facility_external_id=self.facility.external_id, form_code=self.form.code, reference_number=reference
        ).exists()
        if not exists:
            return HttpResponseRedirect(home)
        context = self.base_context(self.form.title)
        context.update(
            reference=reference,
            home_url=home,
            done_timeout=int(plugin_settings.DONE_TIMEOUT_SECONDS),
            idle_timeout=0,
            progress=100,
        )
        return render(request, "patient_feedback/done.html", context)
