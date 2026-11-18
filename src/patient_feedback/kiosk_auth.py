"""
Kiosk authorisation.

Kiosk pages live at /facility/<facility_id>/patient_feedback/. A facility can
have several kiosks, so the browser proves which one it is: it is opened once
with ``?key=<access_key>``, and we then set a signed, HttpOnly cookie scoped
to that facility's URL prefix and redirect to a clean URL, so the key is not
left in the address bar, history or Referer.

The cookie holds the kiosk id and a fingerprint of its current key, so
regenerating the key in the admin revokes every browser using the old one.
The key only lets a browser submit feedback through its own kiosk; it is not
a Care user token and grants no API access.
"""

import hashlib
import uuid

from django.conf import settings
from django.urls import reverse
from django.utils.crypto import constant_time_compare

from patient_feedback.models import FeedbackKiosk
from patient_feedback.settings import plugin_settings

COOKIE_SALT = "patient_feedback.kiosk"


def cookie_name(facility_external_id) -> str:
    return f"pf_kiosk_{uuid.UUID(str(facility_external_id)).hex}"


def cookie_path(facility_external_id) -> str:
    return reverse("patient_feedback:start", kwargs={"facility_id": facility_external_id})


def key_fingerprint(kiosk) -> str:
    return hashlib.sha256(kiosk.access_key.encode()).hexdigest()[:32]


def _max_age_seconds() -> int:
    return int(plugin_settings.KIOSK_COOKIE_MAX_AGE_DAYS) * 24 * 60 * 60


def _kiosks(facility_external_id):
    return FeedbackKiosk.objects.select_related("facility").filter(facility__external_id=facility_external_id)


def kiosk_for_key(facility_external_id, provided_key: str | None) -> FeedbackKiosk | None:
    """The facility's kiosk whose access key matches, compared in constant time."""
    if not provided_key:
        return None
    for kiosk in _kiosks(facility_external_id):
        if constant_time_compare(provided_key, kiosk.access_key):
            return kiosk
    return None


def kiosk_from_cookie(request, facility_external_id) -> FeedbackKiosk | None:
    value = request.get_signed_cookie(
        cookie_name(facility_external_id), default=None, salt=COOKIE_SALT, max_age=_max_age_seconds()
    )
    if not value:
        return None
    kiosk_id, _, fingerprint = value.partition(":")
    try:
        kiosk_id = uuid.UUID(kiosk_id)
    except ValueError:
        return None
    kiosk = _kiosks(facility_external_id).filter(external_id=kiosk_id).first()
    if kiosk is None or not constant_time_compare(fingerprint, key_fingerprint(kiosk)):
        return None
    return kiosk


def authorise(response, kiosk) -> None:
    facility_id = kiosk.facility.external_id
    response.set_signed_cookie(
        cookie_name(facility_id),
        f"{kiosk.external_id}:{key_fingerprint(kiosk)}",
        salt=COOKIE_SALT,
        max_age=_max_age_seconds(),
        path=cookie_path(facility_id),
        httponly=True,
        secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
        samesite="Lax",
    )
