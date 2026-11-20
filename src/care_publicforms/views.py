"""
Public, server-rendered feedback pages: no login, kiosk key, session or
cookies. Anyone in the hospital can open them.

  /facility/<id>/care_publicforms/                     form chooser (or straight to the only form)
  /facility/<id>/type/<form>/care_publicforms/         the whole questionnaire on one page; POST saves it
  /facility/<id>/type/<form>/care_publicforms/done/?ref=…   thank you + reference number

The questionnaire page holds every step (identify, details, ratings, open
questions, review) and every offered language; kiosk.js moves between the steps in
the browser and the page is posted once at the end. Without JavaScript each
step button posts the page and the server shows the next step (steps.py):
the same steps, one page per step, still with no session.

A screen can set its own options in the URL: ?lang=kn (starting language),
?scan=camera|scanner|off and ?keypad=0|1. A screen opened on a form's URL
stays on that form; one opened on the chooser returns to the chooser.

The language the patient picks travels with them as ?language=kn: from the
chooser to the form (and Back / Home / Reset), and through the submit to the
thank-you page. The idle reset and the thank-you page's return go back to the
screen's starting language for the next patient.
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

from care_publicforms.i18n import BASE_LANGUAGE, languages, localize, normalize_language
from care_publicforms.models import FeedbackSubmission, QuestionType
from care_publicforms.questionnaire import (
    FormSpec,
    applies,
    choice_labels,
    comment_key,
    forms_for_facility,
    rating_labels,
)
from care_publicforms.services import (
    collect_answers,
    create_submission,
    digits_of,
    parse_uhid,
    uhid_groups,
    uhid_length,
)
from care_publicforms.settings import plugin_settings
from care_publicforms.steps import FLOW_STEPS, NAV_STEPS, Place, flow_units, navigate, review_rows

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
        # The patient's own language choice, if they made one.
        params = request.POST if request.method == "POST" else request.GET
        self.patient_language = params.get("language") if params.get("language") in languages() else None
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
        if params.get("lang") in languages():
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
    def language(self) -> str:
        """The language to show: the patient's choice, else the screen's starting language."""
        return self.patient_language or self.default_language

    def carry(self) -> dict:
        """Query that keeps the patient's language on links within their visit."""
        return {"language": self.patient_language} if self.patient_language else {}

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
        url = reverse(f"care_publicforms:{name}", kwargs={"facility_id": self.facility.external_id, **kwargs})
        query = {**self.options, **(query or {})}
        return f"{url}?{urlencode(query)}" if query else url

    def chooser_url(self, **query) -> str:
        return self._url("start", query)

    def form_url(self, form, **query) -> str:
        return self._url("form", query, form=form.code)

    def home_url(self, came_from_chooser: bool, **query) -> str:
        """Where the next patient starts: the chooser, or this form if the screen was opened on it."""
        if came_from_chooser and len(self.forms) > 1:
            return self.chooser_url(**query)
        return self.form_url(self.form, **query)

    # ── rendering ────────────────────────────────────────────────────
    def render_empty(self, reason: str):
        return render(self.request, "care_publicforms/empty.html", {"reason": reason}, status=404)

    def language_link(self, code) -> str:
        """The toggle's link without JavaScript: this page in ``code``, keeping its other parameters."""
        query = self.request.GET.copy()
        query["language"] = code
        return f"?{query.urlencode()}"

    def base_context(self, title) -> dict:
        lang = self.language
        return {
            "facility_name": self.facility.name,
            "title": title,
            "title_text": localize(title, lang) if isinstance(title, dict) else "",
            "lang": lang,
            "languages": [
                {
                    "code": code,
                    "label": meta["toggle"],
                    "name": meta["name"],
                    "font": meta["font"],
                    "tall_script": meta["tall_script"],
                    "active": code == lang,
                    "url": self.language_link(code),
                }
                for code, meta in languages().items()
            ],
            "web_fonts": [meta["font"] for meta in languages().values() if meta["font"]],
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
                "url": self.form_url(form, **{"from": "start"}, **self.carry()),
            }
            for form in self.forms
        ]
        context = self.base_context(None)
        # A patient who switched language here and left: back to the screen's language.
        context.update(options=options, home_url=self.chooser_url(), idle_armed=bool(self.patient_language))
        return render(request, "care_publicforms/choose.html", context)


# ── The questionnaire ──────────────────────────────────────────────────
@method_decorator(csrf_exempt, name="dispatch")  # public form with no session or cookies to protect
class FormView(FeedbackPage):
    def get(self, request, **kwargs):
        return self.render_form(came_from_chooser=request.GET.get("from") == "start")

    def post(self, request, **kwargs):
        came_from_chooser = request.POST.get("from") == "start"
        spec = FormSpec(self.form)
        nav = request.POST.get("nav") or "submit"
        if nav != "submit":
            return self.navigate(came_from_chooser, spec, nav)
        if self.rate_limited(request):
            return self.render_form(came_from_chooser, spec, data=request.POST, banner="too_many", status=429)

        raw_uhid = digits_of(request.POST.get("uhid"))
        uhid = parse_uhid(raw_uhid) if raw_uhid else ""
        answers, missing = collect_answers(spec, request.POST, identified=bool(uhid))
        if uhid is None:
            missing["uhid"] = "length"
        if missing:
            return self.render_form(came_from_chooser, spec, data=request.POST, errors=missing, banner="error_summary")

        language = normalize_language(request.POST.get("language"), self.default_language)
        submission = create_submission(self.facility, self.form, language, uhid or "", answers)
        query = {
            "ref": submission.reference_number,
            **({"from": "start"} if came_from_chooser else {}),
            "language": language,  # the thank-you page stays in the patient's language
        }
        return HttpResponseRedirect(self._url("done", query, form=self.form.code))

    def navigate(self, came_from_chooser, spec, nav):
        """Without JavaScript: a step button was pressed; show the step it leads to (nothing is saved)."""
        data = self.request.POST.copy()
        if nav.startswith("lang:") and nav[len("lang:") :] in languages():
            self.patient_language = data["language"] = nav[len("lang:") :]
        raw_uhid = digits_of(data.get("uhid"))
        uhid_valid = parse_uhid(raw_uhid) is not None if raw_uhid else False
        place, errors, _ = navigate(spec, data, nav, identified=uhid_valid, uhid_valid=uhid_valid)
        return self.render_form(came_from_chooser, spec, data=data, errors=errors, place=place)

    @staticmethod
    def rate_limited(request) -> bool:
        """Per IP address (see README for proxies); an empty SUBMIT_RATE_LIMIT turns it off."""
        rate = plugin_settings.SUBMIT_RATE_LIMIT
        if not rate or getattr(settings, "DISABLE_RATELIMIT", False):
            return False
        return is_ratelimited(request, group="care_publicforms.submit", key="ip", rate=rate, increment=True)

    def render_form(
        self, came_from_chooser: bool, spec=None, data=None, errors=None, banner=None, status=200, place=None
    ):
        data = data or {}
        errors = errors or {}
        spec = spec or FormSpec(self.form)
        uhid = digits_of(data.get("uhid"))[: uhid_length()]
        identified = len(uhid) == uhid_length()
        gaps, position = set(), 0
        for size in uhid_groups()[:-1]:
            position += size
            gaps.add(position)
        shown_ratings = [q for q in spec.ratings if applies(q, identified)]

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
                "error": errors.get(question.key),  # "required", "invalid" or None
                # Asked of this patient (guest or identified)? kiosk.js recomputes it as they go.
                "shown": applies(question, identified),
            }
            if question.type == QuestionType.RATING:
                item.update(
                    index=index,
                    number=shown_ratings.index(question) + 1 if question in shown_ratings else index + 1,
                    options=[{"value": str(v), "label": label} for v, label in rating_labels(question).items()],
                )
            elif question.type == QuestionType.CHOICE:
                options = choice_labels(question)
                item.update(
                    options=[{"value": code, "label": labels} for code, labels in options.items()],
                    compact=all(len(localize(labels, BASE_LANGUAGE)) <= 12 for labels in options.values()),
                    # On the "in your own words" step, 2–3 options are large buttons (e.g. Yes / No).
                    buttons=question.step == "open" and 2 <= len(options) <= 3,
                    allow_comment=question.allow_comment,
                    comment_key=comment_key(question),
                    comment=data.get(comment_key(question), ""),
                )
            return item

        ratings = [field(q, i) for i, q in enumerate(spec.ratings)]
        details = [field(q) for q in spec.details]
        open_questions = [field(q) for q in spec.open_questions]

        if place is None:
            # After a failed submit, open the first step with a problem; when only
            # rate-limited, the review, so the patient can simply submit again.
            place = Place()
            if banner == "too_many":
                place.step = "review"
            elif errors:
                if "uhid" in errors:
                    place.step = "uhid"
                elif any(f["error"] for f in details):
                    place.step = "details"
                elif any(r["error"] for r in ratings):
                    place.step, place.card = "questions", next(r["index"] for r in ratings if r["error"])
                else:
                    place.step = "comments"
        in_flow = place.step in FLOW_STEPS
        units = flow_units(spec, identified)
        progress = 0
        if in_flow and place.unit in units:
            progress = round((units.index(place.unit) + 1) / (len(units) + 1) * 100)

        context = self.base_context(self.form.title)
        context.update(
            home_url=self.home_url(came_from_chooser),  # idle reset: the next patient
            # Start the idle timer at once when the page holds a patient's choices
            # (their answers after a failed submit, their language, their form).
            idle_armed=bool(data) or bool(self.patient_language) or came_from_chooser,
            nav_home_url=self.home_url(came_from_chooser, **self.carry()),
            reset_url=self.form_url(self.form, **({"from": "start"} if came_from_chooser else {}), **self.carry()),
            back_to_chooser=(self.chooser_url(**self.carry()) if came_from_chooser and len(self.forms) > 1 else None),
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
            # Where the page opens; without JavaScript, the only step shown.
            current_step=place.step,
            current_card=place.card,
            returning=place.returning,
            identified=identified,
            rating_total=len(shown_ratings),
            progress=progress,
            nav_shown=place.step in NAV_STEPS,
            id_strip_shown=identified and in_flow,
            uhid_display=" ".join(
                uhid[start:end] for start, end in zip([0, *sorted(gaps)], [*sorted(gaps), len(uhid)], strict=False)
            ),
            review_rows=review_rows(spec, data, identified),
            language_form="feedback",  # the language toggle posts the form, keeping the answers
        )
        return render(self.request, "care_publicforms/form.html", context, status=status)


# ── Thank you ──────────────────────────────────────────────────────────
class DoneView(FeedbackPage):
    def get(self, request, **kwargs):
        came_from_chooser = request.GET.get("from") == "start"
        home = self.home_url(came_from_chooser)
        reference = request.GET.get("ref", "")
        exists = FeedbackSubmission.objects.filter(
            facility_external_id=self.facility.external_id, form=self.form, reference_number=reference
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
        return render(request, "care_publicforms/done.html", context)
