"""
Kiosk authorisation.

A kiosk browser proves itself once with ``?key=<access_key>``. We then set a
signed, HttpOnly cookie scoped to that kiosk's URL prefix and redirect to a
clean URL, so the key is not left in the address bar, history or Referer.

The cookie holds a fingerprint of the current key, so regenerating the key
in the admin revokes every browser that was using the old one. The key only
lets a browser submit feedback for its own kiosk; it is not a Care user
token and grants no API access.
"""

import hashlib

from django.conf import settings
from django.urls import reverse
from django.utils.crypto import constant_time_compare

from patient_feedback.settings import plugin_settings

COOKIE_SALT = "patient_feedback.kiosk"


def cookie_name(kiosk) -> str:
    return f"pf_kiosk_{kiosk.external_id.hex}"


def cookie_path(kiosk) -> str:
    return reverse("patient_feedback:start", kwargs={"kiosk_id": kiosk.external_id})


def key_fingerprint(kiosk) -> str:
    return hashlib.sha256(kiosk.access_key.encode()).hexdigest()[:32]


def _max_age_seconds() -> int:
    return int(plugin_settings.KIOSK_COOKIE_MAX_AGE_DAYS) * 24 * 60 * 60


def key_matches(kiosk, provided_key: str | None) -> bool:
    return bool(provided_key) and constant_time_compare(provided_key, kiosk.access_key)


def is_authorised(request, kiosk) -> bool:
    value = request.get_signed_cookie(cookie_name(kiosk), default=None, salt=COOKIE_SALT, max_age=_max_age_seconds())
    return value is not None and constant_time_compare(value, key_fingerprint(kiosk))


def authorise(response, kiosk) -> None:
    response.set_signed_cookie(
        cookie_name(kiosk),
        key_fingerprint(kiosk),
        salt=COOKIE_SALT,
        max_age=_max_age_seconds(),
        path=cookie_path(kiosk),
        httponly=True,
        secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
        samesite="Lax",
    )
