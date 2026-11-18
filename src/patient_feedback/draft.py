"""
The in-progress questionnaire, kept in the Django session (one per kiosk).

Every screen is a server-rendered page, so the answers given so far live on
the server between requests. Nothing is written to the database until the
patient submits on the review screen.
"""

import time

from django.utils import timezone

from patient_feedback.i18n import normalize_language
from patient_feedback.models import IdentificationMethod


def _blank(lang: str, form_id: str | None = None) -> dict:
    return {
        "lang": lang,
        "form": form_id,  # FeedbackForm.external_id as str
        "method": None,  # IdentificationMethod value once the patient picked a path
        "uhid": "",
        "uhid_input": "",  # partially typed UHID (no-JS keypad / language switch)
        "patient_id": None,
        "answers": {},  # {question_key: value}; "<key>__comment" for yes/no reasons
        "details_done": False,
        "open_done": False,
        "started_at": None,
        "last_activity": None,
    }


class Draft:
    def __init__(self, request, kiosk):
        self.request = request
        self.kiosk = kiosk
        self.session_key = f"patient_feedback:{kiosk.external_id}"
        stored = request.session.get(self.session_key)
        self.data = _blank(kiosk.default_language)
        if isinstance(stored, dict) and "answers" in stored:
            self.data.update(stored)
        self.data["lang"] = normalize_language(self.data.get("lang"), kiosk.default_language)

    # ── persistence ──────────────────────────────────────────────────
    def save(self):
        self.data["last_activity"] = time.time()
        self.request.session[self.session_key] = self.data
        self.request.session.modified = True

    def reset(self, keep_language: bool = True, keep_form: bool = False):
        lang = self.data["lang"] if keep_language else self.kiosk.default_language
        self.data = _blank(lang, self.data["form"] if keep_form else None)
        self.save()

    def is_stale(self, idle_seconds: int) -> bool:
        last = self.data.get("last_activity")
        return bool(self.data.get("method")) and last is not None and time.time() - last > idle_seconds

    def touch_started(self):
        if not self.data.get("started_at"):
            self.data["started_at"] = timezone.now().isoformat()

    # ── accessors ────────────────────────────────────────────────────
    @property
    def lang(self) -> str:
        return self.data["lang"]

    @lang.setter
    def lang(self, value: str):
        self.data["lang"] = normalize_language(value, self.kiosk.default_language)

    @property
    def form_id(self) -> str | None:
        return self.data.get("form")

    def choose_form(self, form_id: str):
        """Start on a form; switching forms drops answers given for another one."""
        if self.data.get("form") != form_id:
            lang = self.data["lang"]
            self.data = _blank(lang, form_id)

    @property
    def method(self) -> str | None:
        return self.data.get("method")

    @property
    def is_identified(self) -> bool:
        return self.method in IdentificationMethod.values

    @property
    def answers(self) -> dict:
        return self.data["answers"]

    def set_answer(self, key: str, value):
        if value is None or value == "":
            self.data["answers"].pop(key, None)
        else:
            self.data["answers"][key] = value

    def _set_method(self, method: str):
        # Details asked depend on how the patient identified (e.g. age and
        # sex only for guests), so switching path means asking them again.
        is_guest = method == IdentificationMethod.GUEST
        was_guest = self.data.get("method") == IdentificationMethod.GUEST
        if self.data.get("method") is None or is_guest != was_guest:
            self.data["details_done"] = False
        self.data["method"] = method
        self.touch_started()

    def set_uhid(self, uhid: str, method: str, patient_id: int | None):
        self._set_method(method)
        self.data.update(uhid=uhid, uhid_input=uhid, patient_id=patient_id)

    def set_guest(self):
        # The guest path is anonymous: drop any UHID collected so far.
        self._set_method(IdentificationMethod.GUEST.value)
        self.data.update(uhid="", uhid_input="", patient_id=None)
