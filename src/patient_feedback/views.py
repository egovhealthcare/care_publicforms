"""
Server-rendered kiosk screens.

Each screen is its own URL and a plain HTML form; answers are kept in the
session (see ``draft.py``) and every POST redirects (Post/Redirect/Get). The
flow therefore works on TV browsers with JavaScript disabled or broken;
``kiosk.js`` only adds the camera scanner, instant keypad, idle reset and a
short highlight before a rating is submitted.

Flow: start → (scan | uhid | guest) → question 1..10 → comments → review → done
"""

import time
from datetime import timedelta

from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views import View

from patient_feedback import kiosk_auth
from patient_feedback.draft import OPEN_FIELDS, Draft
from patient_feedback.i18n import LANGUAGES, localize, translate
from patient_feedback.models import FeedbackKiosk, IdentificationMethod, ScanMode
from patient_feedback.questionnaire import (
    AGE_GROUPS,
    RATING_QUESTIONS,
    SCALE,
    SCALE_VALUES,
    SEXES,
    normalize_clinics,
)
from patient_feedback.services import (
    create_response,
    digits_of,
    find_patient_id,
    format_uhid,
    parse_uhid,
    uhid_groups,
    uhid_length,
)
from patient_feedback.settings import plugin_settings

TOTAL_STEPS = 12
STEP_INDEX = {"start": 0, "scan": 0.4, "uhid": 0.4, "guest": 1, "comments": 11, "review": 11.6, "done": 12}
NAV_SCREENS = {"question", "comments", "review"}
FORM_ID = "screen-form"
LAST_SUBMISSION_TTL = 10 * 60  # seconds the "Thank you" screen can be shown again


class KioskView(View):
    """Loads the kiosk, checks the kiosk cookie and the session draft."""

    screen = ""
    template_name = ""
    requires_identity = False
    requires_all_ratings = False

    # ── request lifecycle ───────────────────────────────────────────
    def dispatch(self, request, *args, **kwargs):
        self.kiosk = get_object_or_404(
            FeedbackKiosk.objects.select_related("facility"), external_id=kwargs.pop("kiosk_id")
        )

        if "key" in request.GET:
            if not kiosk_auth.key_matches(self.kiosk, request.GET.get("key")):
                return self.render_blocked("unauthorised")
            # Remember this browser, then drop the key from the address bar.
            response = HttpResponseRedirect(self.url("start"))
            kiosk_auth.authorise(response, self.kiosk)
            return response
        if not kiosk_auth.is_authorised(request, self.kiosk):
            return self.render_blocked("unauthorised")
        if not self.kiosk.is_active:
            return self.render_blocked("inactive")

        self.mark_seen()
        self.draft = Draft(request, self.kiosk)
        if self.draft.is_stale(int(plugin_settings.DRAFT_EXPIRY_SECONDS)):
            # Someone walked away mid-way: never mix their answers with the next patient's.
            self.draft.reset(keep_language=False)
            if self.screen != "start":
                return HttpResponseRedirect(self.url("start"))

        response = self.check_access(request) or super().dispatch(request, *args, **kwargs)
        self.draft.save()
        return response

    def check_access(self, request):
        if self.requires_identity and not self.draft.is_identified:
            return HttpResponseRedirect(self.url("start"))
        if self.requires_all_ratings and not self.draft.all_rated:
            return HttpResponseRedirect(self.next_step_url())
        return None

    def mark_seen(self):
        now = timezone.now()
        last_seen = self.kiosk.last_seen_at
        if last_seen is None or now - last_seen > timedelta(minutes=1):
            FeedbackKiosk.objects.filter(pk=self.kiosk.pk).update(last_seen_at=now)

    def render_blocked(self, reason: str):
        return render(
            self.request,
            "patient_feedback/blocked.html",
            {"reason": reason, "kiosk": self.kiosk},
            status=403,
        )

    # ── helpers ─────────────────────────────────────────────────────
    def url(self, name: str, **kwargs) -> str:
        return reverse(f"patient_feedback:{name}", kwargs={"kiosk_id": self.kiosk.external_id, **kwargs})

    def question_url(self, number: int, from_review: bool = False) -> str:
        url = self.url("question", number=number)
        return f"{url}?from=review" if from_review else url

    def next_step_url(self) -> str:
        if not self.draft.is_identified:
            return self.url("start")
        index = self.draft.first_unanswered_index()
        if index is not None:
            return self.question_url(index + 1)
        return self.url("review")

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
        step = STEP_INDEX.get(self.screen, 0)
        return round(step / TOTAL_STEPS * 100)

    def get_context(self, **extra):
        draft = self.draft
        lang = draft.lang
        current = self.request.get_full_path()
        show_nav = self.screen in NAV_SCREENS
        idle_enabled = bool(draft.method) or lang != self.kiosk.default_language or self.screen != "start"
        context = {
            "kiosk": self.kiosk,
            "facility_name": self.kiosk.facility.name,
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
            "urls": {
                "start": self.url("start"),
                "scan": self.url("scan"),
                "uhid": self.url("uhid"),
                "guest": self.url("guest"),
                "first_question": self.question_url(1),
                "comments": self.url("comments"),
                "review": self.url("review"),
                "reset": self.url("reset"),
            },
            "idle_timeout": self.idle_timeout() if idle_enabled and self.screen != "done" else 0,
            "today": timezone.localdate(),
            "load_web_fonts": bool(plugin_settings.LOAD_WEB_FONTS),
        }
        context.update(extra)
        return context

    def render_screen(self, status: int = 200, **extra):
        return render(self.request, self.template_name, self.get_context(**extra), status=status)


# ── Start / identify ──────────────────────────────────────────────────
class StartView(KioskView):
    screen = "start"
    template_name = "patient_feedback/start.html"

    def get(self, request):
        return self.render_screen(scan_enabled=self.kiosk.scan_mode != ScanMode.DISABLED)


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
        return HttpResponseRedirect(self.next_step_url())

    def scan_context(self):
        return {"use_camera": self.kiosk.scan_mode == ScanMode.CAMERA, "uhid_length": uhid_length()}


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


# ── Guest details ─────────────────────────────────────────────────────
class GuestView(KioskView):
    screen = "guest"
    template_name = "patient_feedback/guest.html"

    def get(self, request):
        return self.render_form(self.draft.data.get("guest") or {})

    def post(self, request):
        clinics = dict(normalize_clinics(self.kiosk.clinics))
        clinic = request.POST.get("clinic", "")
        age_group = request.POST.get("age_group", "")
        sex = request.POST.get("sex", "")
        selection = {
            "clinic": clinic if clinic in clinics else "",
            "age_group": age_group if age_group in dict(AGE_GROUPS) else "",
            "sex": sex if sex in dict(SEXES) else "",
        }

        if self.switch_language(request) or request.POST.get("action") == "back":
            # Keep the chips the patient already tapped, but don't commit to the guest path yet.
            self.draft.data["guest"] = selection
            target = "start" if request.POST.get("action") == "back" else "guest"
            return HttpResponseRedirect(self.url(target))

        self.draft.set_guest(**selection)
        return HttpResponseRedirect(self.next_step_url())

    def render_form(self, selection: dict):
        groups = [
            {"name": "clinic", "title": "guest_clinic", "options": normalize_clinics(self.kiosk.clinics), "kind": ""},
            {"name": "age_group", "title": "guest_age", "options": AGE_GROUPS, "kind": "chips--wide chips--num"},
            {"name": "sex", "title": "guest_sex", "options": SEXES, "kind": "chips--wide"},
        ]
        for group in groups:
            group["selected"] = selection.get(group["name"], "")
        return self.render_screen(form_id=FORM_ID, groups=groups)


# ── Rating questions ──────────────────────────────────────────────────
class QuestionView(KioskView):
    screen = "question"
    template_name = "patient_feedback/question.html"
    requires_identity = True

    def dispatch(self, request, *args, **kwargs):
        self.number = kwargs.pop("number")
        return super().dispatch(request, *args, **kwargs)

    def check_access(self, request):
        denied = super().check_access(request)
        if denied:
            return denied
        if not 1 <= self.number <= len(RATING_QUESTIONS):
            return HttpResponseRedirect(self.next_step_url())
        first_open = self.draft.first_unanswered_index()
        if first_open is not None and self.number - 1 > first_open:
            # No skipping ahead past an unanswered question.
            return HttpResponseRedirect(self.question_url(first_open + 1))
        return None

    def progress(self) -> int:
        return round(self.number / TOTAL_STEPS * 100)

    @property
    def question(self):
        return RATING_QUESTIONS[self.number - 1]

    def get(self, request):
        from_review = request.GET.get("from") == "review"
        selected = self.draft.ratings.get(self.question.key)
        if self.number > 1:
            back_url = self.question_url(self.number - 1)
        elif self.draft.method == IdentificationMethod.GUEST:
            back_url = self.url("guest")
        else:
            back_url = self.url("start")
        if selected is None:
            next_url = None
        elif from_review:
            next_url = self.url("review")
        elif self.number < len(RATING_QUESTIONS):
            next_url = self.question_url(self.number + 1)
        else:
            next_url = self.url("comments")
        return self.render_screen(
            question=self.question,
            number=self.number,
            total=len(RATING_QUESTIONS),
            options=[{"value": value, "label": SCALE[value], "selected": value == selected} for value in SCALE_VALUES],
            from_review=from_review,
            back_url=back_url,
            next_url=next_url,
        )

    def post(self, request):
        try:
            value = int(request.POST.get("rating", ""))
        except ValueError:
            value = None
        if value not in SCALE:
            return HttpResponseRedirect(self.question_url(self.number))
        self.draft.set_rating(self.question.key, value)

        if request.POST.get("return_to") == "review" and self.draft.all_rated:
            return HttpResponseRedirect(self.url("review"))
        if self.number < len(RATING_QUESTIONS):
            return HttpResponseRedirect(self.question_url(self.number + 1))
        return HttpResponseRedirect(self.url("comments"))


# ── Open-ended questions ──────────────────────────────────────────────
class CommentsView(KioskView):
    screen = "comments"
    template_name = "patient_feedback/comments.html"
    requires_identity = True
    requires_all_ratings = True

    def get(self, request):
        return self.render_screen(form_id=FORM_ID, answers=self.draft.data)

    def post(self, request):
        would_return = {"yes": True, "no": False}.get(request.POST.get("would_return"))
        self.draft.set_open_answers(would_return, {field: request.POST.get(field, "") for field in OPEN_FIELDS})

        if self.switch_language(request):
            return HttpResponseRedirect(self.url("comments"))
        if request.POST.get("action") == "back":
            return HttpResponseRedirect(self.question_url(len(RATING_QUESTIONS)))
        return HttpResponseRedirect(self.url("review"))


# ── Review & submit ───────────────────────────────────────────────────
class ReviewView(KioskView):
    screen = "review"
    template_name = "patient_feedback/review.html"
    requires_identity = True
    requires_all_ratings = True

    def check_access(self, request):
        # A double-tap on "Submit" sends a second POST after the draft was
        # cleared: show the reference number again instead of the start.
        if request.method == "POST" and not self.draft.is_identified and last_submission(request, self.kiosk):
            return HttpResponseRedirect(self.url("done"))
        return super().check_access(request)

    def get(self, request):
        lang = self.draft.lang
        not_answered = translate("not_answered", lang)
        rows = []
        for index, question in enumerate(RATING_QUESTIONS):
            value = self.draft.ratings.get(question.key)
            rows.append(
                {
                    "label": localize(question.short, lang),
                    "value": localize(SCALE[value], lang) if value in SCALE else not_answered,
                    "empty": value not in SCALE,
                    "url": self.question_url(index + 1, from_review=True),
                }
            )
        would_return = self.draft.data.get("would_return")
        rows.append(
            {
                "label": translate("review_would_return", lang),
                "value": not_answered if would_return is None else translate("yes" if would_return else "no", lang),
                "empty": would_return is None,
                "url": self.url("comments"),
            }
        )
        return self.render_screen(rows=rows)

    def post(self, request):
        response = create_response(self.kiosk, self.draft)
        request.session[last_submission_key(self.kiosk)] = {
            "reference": response.reference_number,
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

    def get(self, request):
        submission = last_submission(request, self.kiosk)
        if not submission:
            return HttpResponseRedirect(self.url("start"))
        return self.render_screen(
            reference=submission["reference"],
            done_timeout=int(plugin_settings.DONE_TIMEOUT_SECONDS),
            idle_reset_url=f"{self.url('reset')}?idle=1",
        )


# ── Reset & language ──────────────────────────────────────────────────
class ResetView(KioskView):
    screen = "reset"

    def get(self, request):
        # ?idle=1 comes from the idle timer / done screen: the next person
        # starts in the kiosk's default language.
        self.draft.reset(keep_language=request.GET.get("idle") != "1")
        request.session.pop(last_submission_key(self.kiosk), None)
        return HttpResponseRedirect(self.url("start"))

    post = get


class LanguageView(KioskView):
    screen = "language"

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
