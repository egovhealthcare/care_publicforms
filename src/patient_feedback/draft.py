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
from patient_feedback.questionnaire import QUESTION_KEYS, SCALE

OPEN_FIELDS = ("would_return_reason", "improvement", "reason_for_choosing", "suggestions")
MAX_TEXT_LENGTH = 2000


def _blank(lang: str) -> dict:
    return {
        "lang": lang,
        "method": None,  # IdentificationMethod value once the patient picked a path
        "uhid": "",
        "uhid_input": "",  # partially typed UHID (no-JS keypad / language switch)
        "patient_id": None,
        "guest": {"clinic": "", "age_group": "", "sex": ""},
        "ratings": {},
        "would_return": None,
        **dict.fromkeys(OPEN_FIELDS, ""),
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
        if isinstance(stored, dict):
            self.data.update(stored)
        self.data["lang"] = normalize_language(self.data.get("lang"), kiosk.default_language)

    # ── persistence ──────────────────────────────────────────────────
    def save(self):
        self.data["last_activity"] = time.time()
        self.request.session[self.session_key] = self.data
        self.request.session.modified = True

    def reset(self, keep_language: bool = True):
        lang = self.data["lang"] if keep_language else self.kiosk.default_language
        self.data = _blank(lang)
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
    def method(self) -> str | None:
        return self.data.get("method")

    @property
    def is_identified(self) -> bool:
        return self.method in IdentificationMethod.values

    @property
    def ratings(self) -> dict:
        return self.data["ratings"]

    def set_rating(self, key: str, value: int):
        if key in QUESTION_KEYS and value in SCALE:
            self.data["ratings"][key] = value

    def first_unanswered_index(self) -> int | None:
        for index, key in enumerate(QUESTION_KEYS):
            if key not in self.ratings:
                return index
        return None

    @property
    def all_rated(self) -> bool:
        return self.first_unanswered_index() is None

    def set_uhid(self, uhid: str, method: str, patient_id: int | None):
        self.data.update(method=method, uhid=uhid, uhid_input=uhid, patient_id=patient_id)
        self.data["guest"] = {"clinic": "", "age_group": "", "sex": ""}
        self.touch_started()

    def set_guest(self, clinic: str, age_group: str, sex: str):
        # The guest path is anonymous: drop any UHID collected so far.
        self.data.update(method=IdentificationMethod.GUEST.value, uhid="", uhid_input="", patient_id=None)
        self.data["guest"] = {"clinic": clinic, "age_group": age_group, "sex": sex}
        self.touch_started()

    def set_open_answers(self, would_return: bool | None, texts: dict):
        self.data["would_return"] = would_return
        for field in OPEN_FIELDS:
            self.data[field] = (texts.get(field) or "").strip()[:MAX_TEXT_LENGTH]
