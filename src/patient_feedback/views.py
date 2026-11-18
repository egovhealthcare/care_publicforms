"""
Server-rendered kiosk screens.

Each screen is its own URL and a plain HTML form; answers are kept in the
session (see ``draft.py``) and every POST redirects (Post/Redirect/Get). The
flow therefore works on TV browsers with JavaScript disabled or broken;
``kiosk.js`` only adds the camera scanner, instant keypad, idle reset and a
short highlight before a rating is submitted.

Pages live under /facility/<facility_id>/patient_feedback/ (see apps.py), and
every step of a form under /<form code>/, e.g. .../patient_feedback/ipd/.
The questions come from the configured FeedbackForm (see questionnaire.py):

  start (choose OP / IP form, if the kiosk offers more than one)
    → <form>/ identify → (scan | uhid | guest)
    → details  (choice / date questions, if any)
    → questions (every rating on one page, one card at a time)
    → comments (yes/no and free-text questions, if any)
    → review → done
"""

import math
import time
from datetime import timedelta

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views import View

from patient_feedback import kiosk_auth
from patient_feedback.draft import Draft
from patient_feedback.i18n import LANGUAGES, localize, translate
from patient_feedback.models import FeedbackKiosk, IdentificationMethod, QuestionType, ScanMode
from patient_feedback.questionnaire import (
    FormSpec,
    choice_labels,
    clean_text,
    comment_key,
    display_answer,
    forms_for_kiosk,
    parse_answer,
    rating_labels,
)
from patient_feedback.services import (
    create_submission,
    digits_of,
    find_patient_id,
    format_uhid,
    parse_uhid,
    uhid_groups,
    uhid_length,
)
from patient_feedback.settings import plugin_settings

NAV_SCREENS = {"question", "comments", "review"}
FORM_ID = "screen-form"
LAST_SUBMISSION_TTL = 10 * 60  # seconds the "Thank you" screen can be shown again
SECONDS_PER_QUESTION = 12  # for "about N minutes" on the identify screen
# Steps of a form; their URLs carry the form code.
FORM_PAGES = {"identify", "scan", "uhid", "guest", "details", "questions", "comments", "review"}


class KioskView(View):
    """Loads the kiosk, its forms and the session draft; checks the kiosk cookie."""

    screen = ""
    template_name = ""
    requires_form = True
    requires_identity = False

    # ── request lifecycle ───────────────────────────────────────────
    def dispatch(self, request, *args, **kwargs):
        facility_id = kwargs.pop("facility_id")
        form_code = kwargs.pop("form", None)
        self.kiosk = None
        self.form = None

        if "key" in request.GET:
            self.kiosk = kiosk_auth.kiosk_for_key(facility_id, request.GET.get("key"))
            if self.kiosk is None:
                return self.render_blocked("unauthorised")
            # Remember this browser, then drop the key from the address bar
            # (keeping the path, so a link to one form stays on that form).
            response = HttpResponseRedirect(request.path)
            kiosk_auth.authorise(response, self.kiosk)
            return response
        # Unknown facilities get the same answer as a missing cookie, so
        # facility ids can't be probed through this page.
        self.kiosk = kiosk_auth.kiosk_from_cookie(request, facility_id)
        if self.kiosk is None:
            return self.render_blocked("unauthorised")
        if not self.kiosk.is_active:
            return self.render_blocked("inactive")

        self.mark_seen()
        self.draft = Draft(request, self.kiosk)
        self.forms = forms_for_kiosk(self.kiosk)
        if self.draft.is_stale(int(plugin_settings.DRAFT_EXPIRY_SECONDS)):
            # Someone walked away mid-way: never mix their answers with the next patient's.
            self.draft.reset(keep_language=False)
            if self.screen not in ("start", "identify"):
                return HttpResponseRedirect(self.home_url())

        if form_code is not None:
            self.form = next((f for f in self.forms if f.code == form_code), None)
            if self.form is None:  # unknown, inactive or not offered on this kiosk
                return HttpResponseRedirect(self.url("start"))
            self.draft.choose_form(str(self.form.external_id))
        else:
            self.form = next((f for f in self.forms if str(f.external_id) == self.draft.form_id), None)
        self.spec = FormSpec(self.form, self.draft.method) if self.form else None

        response = self.check_access(request) or super().dispatch(request, *args, **kwargs)
        self.draft.save()
        return response

    def check_access(self, request):
        if not self.forms and self.screen not in ("reset", "language"):
            return self.render_blocked("no_forms")
        if self.requires_form and self.form is None:
            return HttpResponseRedirect(self.url("start"))
        if self.requires_identity and not self.draft.is_identified:
            return HttpResponseRedirect(self.identify_url())
        return None

    def mark_seen(self):
        now = timezone.now()
        last_seen = self.kiosk.last_seen_at
        if last_seen is None or now - last_seen > timedelta(minutes=1):
            FeedbackKiosk.objects.filter(pk=self.kiosk.pk).update(last_seen_at=now)

    def render_blocked(self, reason: str):
        return render(self.request, "patient_feedback/blocked.html", {"reason": reason}, status=403)

    # ── navigation ──────────────────────────────────────────────────
    def url(self, name: str, **kwargs) -> str:
        if name in FORM_PAGES and "form" not in kwargs:
            kwargs["form"] = self.form.code
        return reverse(f"patient_feedback:{name}", kwargs={"facility_id": self.kiosk.facility.external_id, **kwargs})

    def identify_url(self, via: str = "flow", form=None) -> str:
        """
        The form's first step, reached from inside the kiosk. The ``from``
        marker tells it apart from the kiosk being launched on that URL,
        which pins the screen to the form (see IdentifyView).
        """
        return f"{self.url('identify', form=(form or self.form).code)}?{urlencode({'from': via})}"

    # A kiosk's "home" is where idle reset and "Submit another response" go:
    # the form chooser, or one form when the screen was launched on its URL.
    @property
    def home_key(self) -> str:
        return f"patient_feedback:{self.kiosk.external_id}:home"

    @property
    def pinned_form(self):
        code = self.request.session.get(self.home_key) or ""
        return next((f for f in self.forms if f.code == code), None)

    def home_url(self) -> str:
        pinned = self.pinned_form
        return self.url("identify", form=pinned.code) if pinned else self.url("start")

    def question_url(self, number: int, from_review: bool = False) -> str:
        """The questions page opened at question ``number`` (1-based)."""
        query = {"q": number, **({"from": "review"} if from_review else {})}
        return f"{self.url('questions')}?{urlencode(query)}"

    def first_unanswered_rating(self) -> int | None:
        for index, question in enumerate(self.spec.ratings):
            if question.key not in self.draft.answers:
                return index
        return None

    @property
    def all_rated(self) -> bool:
        return self.first_unanswered_rating() is None

    def next_step_url(self) -> str:
        if self.form is None:
            return self.url("start")
        if not self.draft.is_identified:
            return self.identify_url()
        if self.spec.details and not self.draft.data["details_done"]:
            return self.url("details")
        index = self.first_unanswered_rating()
        if index is not None:
            return self.question_url(index + 1)
        if self.spec.open_questions and not self.draft.data["open_done"]:
            return self.url("comments")
        return self.url("review")

    # ── rendering ───────────────────────────────────────────────────
    def idle_timeout(self) -> int:
        return int(plugin_settings.IDLE_TIMEOUT_SECONDS)

    def switch_language(self, request) -> bool:
        """Header language buttons submit the screen's form with ``_lang``."""
        code = request.POST.get("_lang")
        if code in LANGUAGES:
            self.draft.lang = code
            return True
        return False

    def progress(self) -> int:
        if self.spec is None:
            return 0
        details = 1 if self.spec.details else 0
        ratings = len(self.spec.ratings)
        open_step = 1 if self.spec.open_questions else 0
        total = details + ratings + open_step + 1
        position = {
            "identify": 0,
            "scan": 0.4,
            "uhid": 0.4,
            "details": details,
            "comments": details + ratings + 1,
            "review": total - 0.4,
            "done": total,
        }.get(self.screen, 0)
        return round(position / total * 100)

    def get_context(self, **extra):
        draft = self.draft
        lang = draft.lang
        current = self.request.get_full_path()
        show_nav = self.screen in NAV_SCREENS
        idle_enabled = bool(draft.method) or lang != self.kiosk.default_language or self.screen != "start"
        context = {
            "kiosk": self.kiosk,
            "facility_name": self.kiosk.facility.name,
            "form_title": localize(self.form.title, lang) if self.form else translate("kicker", lang),
            "lang": lang,
            "screen": self.screen,
            "progress": self.progress(),
            "show_nav": show_nav,
            "uhid_display": format_uhid(draft.data["uhid"]) if show_nav and draft.data.get("uhid") else "",
            "form_id": None,
            "languages": [
                {
                    "code": code,
                    "label": meta["toggle"],
                    "name": meta["name"],
                    "active": code == lang,
                    "url": f"{self.url('language', code=code)}?{urlencode({'next': current})}",
                }
                for code, meta in LANGUAGES.items()
            ],
            "urls": self.page_urls(),
            "idle_timeout": self.idle_timeout() if idle_enabled and self.screen != "done" else 0,
            "today": timezone.localdate(),
            "load_web_fonts": bool(plugin_settings.LOAD_WEB_FONTS),
        }
        context.update(extra)
        return context

    def page_urls(self) -> dict:
        urls = {"start": self.url("start"), "reset": self.url("reset")}
        if self.form:
            urls.update(
                identify=self.identify_url(),
                scan=self.url("scan"),
                uhid=self.url("uhid"),
                guest=self.url("guest"),
                details=self.url("details"),
                first_question=self.question_url(1),
                comments=self.url("comments"),
                review=self.url("review"),
            )
        return urls

    def render_screen(self, status: int = 200, **extra):
        return render(self.request, self.template_name, self.get_context(**extra), status=status)

    def question_fields(self, questions, errors=None):
        """Template-ready questions for the details and comments screens."""
        lang = self.draft.lang
        answers = self.draft.answers
        errors = errors or {}
        fields = []
        for question in questions:
            value = answers.get(question.key)
            field = {
                "key": question.key,
                "type": question.type,
                "text": localize(question.text, lang),
                "hint": localize(question.hint, lang),
                "required": question.required,
                "error": errors.get(question.key),
                "value": value,
            }
            if question.type == QuestionType.CHOICE:
                field["options"] = [(code, localize(labels, lang)) for code, labels in choice_labels(question).items()]
                field["compact"] = all(len(label) <= 12 for _, label in field["options"])
            if question.type == QuestionType.YES_NO:
                field["allow_comment"] = question.allow_comment
                field["comment_key"] = comment_key(question)
                field["comment"] = answers.get(comment_key(question), "")
            fields.append(field)
        return fields

    def save_answers(self, questions, data) -> dict:
        """Store submitted answers for ``questions``; returns {key: error} for missing required ones."""
        errors = {}
        for question in questions:
            value = parse_answer(question, data.get(question.key))
            self.draft.set_answer(question.key, value)
            if question.type == QuestionType.YES_NO and question.allow_comment:
                self.draft.set_answer(comment_key(question), clean_text(data.get(comment_key(question))))
            if question.required and value is None:
                errors[question.key] = translate("required_error", self.draft.lang)
        return errors


# ── Start: choose a form ──────────────────────────────────────────────
class StartView(KioskView):
    screen = "start"
    template_name = "patient_feedback/choose.html"
    requires_form = False

    def get(self, request):
        if len(self.forms) == 1:
            # Nothing to choose: the kiosk is pinned to its only form.
            return HttpResponseRedirect(self.url("identify", form=self.forms[0].code))
        request.session[self.home_key] = ""  # this kiosk starts at the chooser
        lang = self.draft.lang
        options = [
            {
                "title": localize(form.title, lang),
                "description": localize(form.description, lang),
                "patient_type": form.patient_type,
                "url": self.identify_url("start", form=form),
            }
            for form in self.forms
        ]
        return self.render_screen(options=options)


# ── Identify ──────────────────────────────────────────────────────────
class IdentifyView(KioskView):
    """
    The first step of a form, at /<form code>/. Opened without a ``from``
    marker (the kiosk was launched on this URL, or it has only this form),
    it pins the kiosk to the form: no chooser, and resets come back here.
    """

    screen = "identify"
    template_name = "patient_feedback/start.html"

    def get(self, request):
        if not request.GET.get("from"):
            request.session[self.home_key] = self.form.code
        with_chooser = self.pinned_form is None and len(self.forms) > 1
        minutes = max(1, math.ceil(len(self.spec.questions) * SECONDS_PER_QUESTION / 60))
        return self.render_screen(
            scan_enabled=self.kiosk.scan_mode != ScanMode.DISABLED,
            step=2 if with_chooser else 1,
            question_count=self.spec.rating_count_for_everyone,
            minutes=minutes,
            back_url=self.url("start") if with_chooser else None,
        )


# ── QR scan ───────────────────────────────────────────────────────────
class ScanView(KioskView):
    screen = "scan"
    template_name = "patient_feedback/scan.html"

    def get(self, request):
        if self.kiosk.scan_mode == ScanMode.DISABLED:
            return HttpResponseRedirect(self.url("uhid"))
        return self.render_screen(**self.scan_context())

    def post(self, request):
        if self.kiosk.scan_mode == ScanMode.DISABLED:
            return HttpResponseRedirect(self.url("uhid"))
        uhid = parse_uhid(request.POST.get("code", "")[:512])
        if not uhid:
            return self.render_screen(error="scan_unreadable", **self.scan_context())
        patient_id = find_patient_id(self.kiosk, uhid)
        if patient_id is None and self.kiosk.require_registered_uhid and self.kiosk.patient_identifier_config_id:
            return self.render_screen(error="uhid_error_not_found", **self.scan_context())
        self.draft.set_uhid(uhid, IdentificationMethod.SCAN.value, patient_id)
        self.spec = FormSpec(self.form, self.draft.method)
        return HttpResponseRedirect(self.next_step_url())

    def scan_context(self):
        return {
            "use_camera": self.kiosk.scan_mode == ScanMode.CAMERA,
            "uhid_length": uhid_length(),
            "back_url": self.identify_url(),
        }


# ── Manual UHID ───────────────────────────────────────────────────────
class UhidView(KioskView):
    screen = "uhid"
    template_name = "patient_feedback/uhid.html"
    KEYPAD = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]

    def get(self, request):
        return self.render_entry(self.draft.data.get("uhid_input", ""))

    def post(self, request):
        length = uhid_length()
        digits = digits_of(request.POST.get("uhid", ""))[:length]

        if self.switch_language(request):
            self.draft.data["uhid_input"] = digits
            return HttpResponseRedirect(self.url("uhid"))

        # On-screen keypad without JavaScript: each key is a submit button.
        key = request.POST.get("key")
        if key is not None:
            if key.isdigit() and len(key) == 1:
                digits = (digits + key)[:length]
            elif key == "back":
                digits = digits[:-1]
            elif key == "clear":
                digits = ""
            self.draft.data["uhid_input"] = digits
            return HttpResponseRedirect(self.url("uhid"))

        uhid = parse_uhid(digits)
        if not uhid:
            self.draft.data["uhid_input"] = digits
            return self.render_entry(digits, error="uhid_error_length")
        patient_id = find_patient_id(self.kiosk, uhid)
        if patient_id is None and self.kiosk.require_registered_uhid and self.kiosk.patient_identifier_config_id:
            self.draft.data["uhid_input"] = digits
            return self.render_entry(digits, error="uhid_error_not_found")
        self.draft.set_uhid(uhid, IdentificationMethod.MANUAL.value, patient_id)
        self.spec = FormSpec(self.form, self.draft.method)
        return HttpResponseRedirect(self.next_step_url())

    def render_entry(self, digits: str, error: str | None = None):
        length = uhid_length()
        gap_before = set()
        position = 0
        for size in uhid_groups()[:-1]:
            position += size
            gap_before.add(position)
        cells = [
            {"digit": digits[i] if i < len(digits) else "", "gap": i in gap_before, "active": i == len(digits)}
            for i in range(length)
        ]
        if len(digits) >= length and cells:
            cells[-1]["active"] = True
        return self.render_screen(
            form_id=FORM_ID,
            digits=digits,
            cells=cells,
            uhid_length=length,
            error=error,
            keypad=self.KEYPAD,
            show_keypad=self.kiosk.show_keypad,
        )


# ── Guest ─────────────────────────────────────────────────────────────
class GuestView(KioskView):
    screen = "guest"

    def get(self, request):
        self.draft.set_guest()
        self.spec = FormSpec(self.form, self.draft.method)
        return HttpResponseRedirect(self.next_step_url())


# ── A few details (choice / date questions) ───────────────────────────
class DetailsView(KioskView):
    screen = "details"
    template_name = "patient_feedback/details.html"
    requires_identity = True

    def get(self, request):
        if not self.spec.details:
            return HttpResponseRedirect(self.next_step_url())
        return self.render_form()

    def post(self, request):
        if not self.spec.details:
            return HttpResponseRedirect(self.next_step_url())
        errors = self.save_answers(self.spec.details, request.POST)
        if self.switch_language(request):
            return HttpResponseRedirect(self.url("details"))
        if request.POST.get("action") == "back":
            return HttpResponseRedirect(self.identify_url())
        if errors:
            return self.render_form(errors)
        self.draft.data["details_done"] = True
        return HttpResponseRedirect(self.next_step_url())

    def render_form(self, errors=None):
        return self.render_screen(
            form_id=FORM_ID,
            fields=self.question_fields(self.spec.details, errors),
            is_guest=self.draft.method == IdentificationMethod.GUEST,
        )


# ── Rating questions: one page, one card at a time ───────────────────
class QuestionsView(KioskView):
    """
    All rating questions on one page. The server renders every question and
    marks the current one; only that card is visible.

    With JavaScript (kiosk.js) a tap records the answer in a hidden field,
    saves it in the background (``autosave``) and moves to the next card
    without reloading; the last answer submits the page. Without JavaScript
    each answer button posts ``answer=<key>:<value>`` and the server shows the
    next card, so the same page still works one question at a time.
    """

    screen = "question"
    template_name = "patient_feedback/questions.html"
    requires_identity = True

    def check_access(self, request):
        denied = super().check_access(request)
        if denied:
            return denied
        if self.spec.details and not self.draft.data["details_done"]:
            return HttpResponseRedirect(self.url("details"))
        if not self.spec.ratings:
            return HttpResponseRedirect(self.next_step_url())
        return None

    def start_index(self, requested) -> int:
        """0-based card to show: ?q=N (1-based), but never past the first unanswered one."""
        total = len(self.spec.ratings)
        first_open = self.first_unanswered_rating()
        try:
            index = int(requested) - 1
        except (TypeError, ValueError):
            index = first_open if first_open is not None else 0
        index = max(0, min(index, total - 1))
        if first_open is not None:
            index = min(index, first_open)
        return index

    def progress_steps(self):
        details = 1 if self.spec.details else 0
        total = details + len(self.spec.ratings) + (1 if self.spec.open_questions else 0) + 1
        return details, total

    def progress(self) -> int:
        details, total = self.progress_steps()
        return round((details + self.index + 1) / total * 100)

    def back_url(self) -> str:
        return self.url("details") if self.spec.details else self.identify_url()

    def get(self, request):
        lang = self.draft.lang
        answers = self.draft.answers
        self.index = self.start_index(request.GET.get("q"))
        details, total_steps = self.progress_steps()
        questions = []
        for index, question in enumerate(self.spec.ratings):
            selected = answers.get(question.key)
            questions.append(
                {
                    "index": index,
                    "number": index + 1,
                    "key": question.key,
                    "text": localize(question.text, lang),
                    "hint": localize(question.hint, lang),
                    "label": localize(question.short_text, lang) or localize(question.text, lang),
                    "selected": selected,
                    "options": [
                        {"value": value, "label": localize(label, lang), "selected": value == selected}
                        for value, label in rating_labels(question).items()
                    ],
                }
            )
        return self.render_screen(
            form_id=FORM_ID,
            questions=questions,
            total=len(questions),
            start_index=self.index,
            from_review=request.GET.get("from") == "review",
            back_url=self.back_url(),
            progress_base=details,
            progress_total=total_steps,
        )

    def post(self, request):
        ratings = self.spec.ratings
        by_key = {q.key: (index, q) for index, q in enumerate(ratings)}

        # Answers kept by the page's script in hidden fields
        for question in ratings:
            value = parse_answer(question, request.POST.get(f"rating_{question.key}"))
            if value is not None:
                self.draft.set_answer(question.key, value)
        # An answer button (no JavaScript): "<key>:<value>"
        answered = None
        key, _, raw = (request.POST.get("answer") or "").partition(":")
        if key in by_key:
            index, question = by_key[key]
            value = parse_answer(question, raw)
            if value is not None:
                self.draft.set_answer(question.key, value)
                answered = index

        if request.POST.get("autosave"):
            return HttpResponse(status=204)
        try:
            current = int(request.POST.get("current", 0))
        except ValueError:
            current = 0
        if self.switch_language(request):
            return HttpResponseRedirect(self.question_url(current + 1))

        # Back / Next buttons (no JavaScript, or Back on the first card)
        action, _, raw_index = (request.POST.get("nav") or "").partition(":")
        if action in ("back", "next") and raw_index.isdigit():
            index = int(raw_index)
            if action == "back":
                return HttpResponseRedirect(self.question_url(index) if index > 0 else self.back_url())
            if index + 1 < len(ratings):
                return HttpResponseRedirect(self.question_url(index + 2))
            return HttpResponseRedirect(self.next_step_url())

        if request.POST.get("return_to") == "review" and self.all_rated:
            return HttpResponseRedirect(self.url("review"))
        if answered is not None and answered + 1 < len(ratings):
            return HttpResponseRedirect(self.question_url(answered + 2))
        return HttpResponseRedirect(self.next_step_url())


# ── Yes/no and free-text questions ────────────────────────────────────
class CommentsView(KioskView):
    screen = "comments"
    template_name = "patient_feedback/comments.html"
    requires_identity = True

    def check_access(self, request):
        denied = super().check_access(request)
        if denied:
            return denied
        if not self.all_rated or not self.spec.open_questions:
            return HttpResponseRedirect(self.next_step_url())
        return None

    def get(self, request):
        return self.render_form()

    def post(self, request):
        questions = self.spec.open_questions
        errors = self.save_answers(questions, request.POST)
        if self.switch_language(request):
            return HttpResponseRedirect(self.url("comments"))
        if request.POST.get("action") == "back":
            return HttpResponseRedirect(self.question_url(len(self.spec.ratings)))
        if errors:
            return self.render_form(errors)
        self.draft.data["open_done"] = True
        return HttpResponseRedirect(self.url("review"))

    def render_form(self, errors=None):
        questions = self.spec.open_questions
        heading = "open_heading_required" if any(q.required for q in questions) else "open_heading"
        return self.render_screen(
            form_id=FORM_ID,
            fields=self.question_fields(questions, errors),
            heading=translate(heading, self.draft.lang, n=len(questions)),
        )


# ── Review & submit ───────────────────────────────────────────────────
class ReviewView(KioskView):
    screen = "review"
    template_name = "patient_feedback/review.html"
    requires_identity = True

    def check_access(self, request):
        # A double-tap on "Submit" sends a second POST after the draft was
        # cleared: show the reference number again instead of the start.
        if request.method == "POST" and not self.draft.is_identified and last_submission(request, self.kiosk):
            return HttpResponseRedirect(self.url("done"))
        denied = super().check_access(request)
        if denied:
            return denied
        if self.next_step_url() != self.url("review"):
            return HttpResponseRedirect(self.next_step_url())
        return None

    def get(self, request):
        lang = self.draft.lang
        answers = self.draft.answers
        not_answered = translate("not_answered", lang)
        rating_numbers = {q.key: index + 1 for index, q in enumerate(self.spec.ratings)}
        rows = []
        for question in self.spec.questions:
            value = answers.get(question.key)
            if question.type == QuestionType.RATING:
                url = self.question_url(rating_numbers[question.key], from_review=True)
            elif question.type in (QuestionType.CHOICE, QuestionType.DATE):
                url = self.url("details")
            else:
                url = self.url("comments")
            display = display_answer(question, value, lang)
            if question.type == QuestionType.TEXT and len(display) > 60:
                display = display[:57].rstrip() + "…"
            rows.append(
                {
                    "label": localize(question.short_text, lang) or localize(question.text, lang),
                    "value": display or not_answered,
                    "empty": not display,
                    "url": url,
                }
            )
        return self.render_screen(rows=rows)

    def post(self, request):
        submission = create_submission(self.kiosk, self.spec, self.draft)
        request.session[last_submission_key(self.kiosk)] = {
            "reference": submission.reference_number,
            "at": time.time(),
        }
        self.draft.reset(keep_language=True)
        return HttpResponseRedirect(self.url("done"))


def last_submission_key(kiosk) -> str:
    return f"patient_feedback:{kiosk.external_id}:last"


def last_submission(request, kiosk) -> dict | None:
    value = request.session.get(last_submission_key(kiosk))
    if isinstance(value, dict) and time.time() - value.get("at", 0) < LAST_SUBMISSION_TTL:
        return value
    return None


# ── Thank you ─────────────────────────────────────────────────────────
class DoneView(KioskView):
    screen = "done"
    template_name = "patient_feedback/done.html"
    requires_form = False

    def get(self, request):
        submission = last_submission(request, self.kiosk)
        if not submission:
            return HttpResponseRedirect(self.home_url())
        return self.render_screen(
            reference=submission["reference"],
            done_timeout=int(plugin_settings.DONE_TIMEOUT_SECONDS),
            idle_reset_url=f"{self.url('reset')}?idle=1",
        )


# ── Reset & language ──────────────────────────────────────────────────
class ResetView(KioskView):
    screen = "reset"
    requires_form = False

    def get(self, request):
        # ?idle=1 comes from the idle timer / done screen: the next person
        # starts in the kiosk's default language.
        self.draft.reset(keep_language=request.GET.get("idle") != "1")
        request.session.pop(last_submission_key(self.kiosk), None)
        return HttpResponseRedirect(self.home_url())

    post = get


class LanguageView(KioskView):
    screen = "language"
    requires_form = False

    def get(self, request, code):
        if code in LANGUAGES:
            self.draft.lang = code
        target = request.GET.get("next", "")
        start = self.url("start")
        if not (
            target.startswith(start) and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()})
        ):
            target = start
        return HttpResponseRedirect(target)
