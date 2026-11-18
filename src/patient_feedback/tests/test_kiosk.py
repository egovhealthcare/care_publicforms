import time
from datetime import timedelta
from unittest import mock

from care.emr.models.patient import PatientIdentifier, PatientIdentifierConfig
from care.utils.tests.base import CareAPITestBase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from patient_feedback import kiosk_auth
from patient_feedback.models import FeedbackKiosk, FeedbackResponse, ScanMode
from patient_feedback.questionnaire import QUESTION_KEYS, RATING_QUESTIONS
from patient_feedback.tests import PLAIN_STATIC_STORAGES

UHID = "12345678901"


@override_settings(STORAGES=PLAIN_STATIC_STORAGES)
class KioskTestBase(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.facility = self.create_facility(user=self.user, name="District Hospital, Mysuru")
        self.kiosk = FeedbackKiosk.objects.create(facility=self.facility, name="OPD block")
        self.open_kiosk()

    def url(self, name, kiosk=None, **kwargs):
        kiosk = kiosk or self.kiosk
        return reverse(f"patient_feedback:{name}", kwargs={"kiosk_id": kiosk.external_id, **kwargs})

    def open_kiosk(self, kiosk=None):
        kiosk = kiosk or self.kiosk
        response = self.client.get(self.url("start", kiosk), {"key": kiosk.access_key})
        self.assertEqual(response.status_code, 302)
        return response

    def draft(self, kiosk=None):
        return self.client.session.get(f"patient_feedback:{(kiosk or self.kiosk).external_id}") or {}

    def answer_all(self, value=5, start=1):
        for number in range(start, len(RATING_QUESTIONS) + 1):
            response = self.client.post(self.url("question", number=number), {"rating": value})
            self.assertEqual(response.status_code, 302)
        return response

    def identify_with_uhid(self, uhid=UHID):
        return self.client.post(self.url("uhid"), {"uhid": uhid, "action": "continue"})


class KioskAccessTests(KioskTestBase):
    def test_key_sets_cookie_and_strips_key_from_url(self):
        self.client.cookies.clear()
        response = self.open_kiosk()
        self.assertEqual(response["Location"], self.url("start"))
        cookie = response.cookies[kiosk_auth.cookie_name(self.kiosk)]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], self.url("start"))
        self.assertEqual(self.client.get(self.url("start")).status_code, 200)

    def test_browser_without_cookie_is_blocked(self):
        self.client.cookies.clear()
        response = self.client.get(self.url("start"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "isn't set up as a feedback kiosk", status_code=403)

    def test_wrong_key_is_blocked(self):
        self.client.cookies.clear()
        response = self.client.get(self.url("start"), {"key": "not-the-key"})
        self.assertEqual(response.status_code, 403)

    def test_regenerated_key_revokes_cookie(self):
        self.kiosk.regenerate_access_key()
        self.assertEqual(self.client.get(self.url("start")).status_code, 403)

    def test_cookie_for_one_kiosk_does_not_open_another(self):
        other = FeedbackKiosk.objects.create(facility=self.facility, name="Second")
        self.assertEqual(self.client.get(self.url("start", other)).status_code, 403)

    def test_inactive_kiosk(self):
        self.kiosk.is_active = False
        self.kiosk.save()
        response = self.client.get(self.url("start"))
        self.assertContains(response, "switched off", status_code=403)

    def test_last_seen_is_recorded(self):
        self.client.get(self.url("start"))
        self.kiosk.refresh_from_db()
        self.assertIsNotNone(self.kiosk.last_seen_at)


class UhidFlowTests(KioskTestBase):
    def test_start_screen_renders_facility_and_options(self):
        response = self.client.get(self.url("start"))
        self.assertContains(response, "District Hospital, Mysuru")
        self.assertContains(response, "Tell us about your visit today.")
        self.assertContains(response, self.url("scan"))
        self.assertContains(response, self.url("guest"))

    def test_short_uhid_shows_error(self):
        response = self.identify_with_uhid("12345")
        self.assertContains(response, "Enter all 11 digits of your UHID.")
        self.assertEqual(self.draft()["uhid_input"], "12345")

    def test_full_flow_creates_response(self):
        response = self.identify_with_uhid("123 4567 8901")
        self.assertRedirects(response, self.url("question", number=1), fetch_redirect_response=False)

        page = self.client.get(self.url("question", number=1))
        self.assertContains(page, "Question 1 of 10")
        self.assertContains(page, "123 4567 8901")  # UHID strip

        self.answer_all(value=4)
        self.client.post(self.url("question", number=3), {"rating": 0})  # "No comments"
        response = self.client.post(
            self.url("comments"),
            {"would_return": "yes", "would_return_reason": "Kind staff", "improvement": "Shorter queues"},
        )
        self.assertRedirects(response, self.url("review"), fetch_redirect_response=False)

        review = self.client.get(self.url("review"))
        self.assertContains(review, "Before you send")
        self.assertContains(review, "No comments")

        response = self.client.post(self.url("review"))
        self.assertRedirects(response, self.url("done"), fetch_redirect_response=False)

        saved = FeedbackResponse.objects.get()
        self.assertEqual(saved.identification_method, "manual")
        self.assertEqual(saved.uhid, UHID)
        self.assertEqual(saved.facility, self.facility)
        self.assertEqual(set(saved.ratings), set(QUESTION_KEYS))
        self.assertEqual(saved.ratings["staff_behaviour"], 0)
        self.assertEqual(str(saved.average_rating), "4.00")  # the 0 is not counted
        self.assertTrue(saved.would_return)
        self.assertEqual(saved.improvement, "Shorter queues")
        self.assertIsNotNone(saved.started_at)
        self.assertRegex(saved.reference_number, r"^OPD-\d{8}-\d{4}$")

        done = self.client.get(self.url("done"))
        self.assertContains(done, saved.reference_number)
        self.assertContains(done, 'http-equiv="refresh"')

        # The draft is gone: the next patient starts from scratch.
        self.assertRedirects(self.client.get(self.url("review")), self.url("start"), fetch_redirect_response=False)

    def test_double_submit_shows_reference_again(self):
        self.identify_with_uhid()
        self.answer_all()
        self.client.post(self.url("review"))
        response = self.client.post(self.url("review"))
        self.assertRedirects(response, self.url("done"), fetch_redirect_response=False)
        self.assertEqual(FeedbackResponse.objects.count(), 1)

    def test_keypad_without_javascript(self):
        self.client.post(self.url("uhid"), {"uhid": "12", "key": "3"})
        self.assertEqual(self.draft()["uhid_input"], "123")
        self.client.post(self.url("uhid"), {"uhid": "123", "key": "back"})
        self.assertEqual(self.draft()["uhid_input"], "12")
        self.client.post(self.url("uhid"), {"uhid": "12", "key": "clear"})
        self.assertEqual(self.draft()["uhid_input"], "")
        self.client.post(self.url("uhid"), {"uhid": UHID, "key": "9"})
        self.assertEqual(self.draft()["uhid_input"], UHID)  # capped at 11 digits

    def test_scan_accepts_payload_with_other_characters(self):
        response = self.client.post(self.url("scan"), {"code": "UHID:123-4567-8901"})
        self.assertRedirects(response, self.url("question", number=1), fetch_redirect_response=False)
        self.assertEqual(self.draft()["method"], "scan")

    def test_scan_rejects_payload_without_uhid(self):
        response = self.client.post(self.url("scan"), {"code": "https://example.org/x"})
        self.assertContains(response, "read a UHID from that code")

    def test_scan_disabled_kiosk_hides_scan_option(self):
        self.kiosk.scan_mode = ScanMode.DISABLED
        self.kiosk.save()
        response = self.client.get(self.url("start"))
        self.assertNotContains(response, self.url("scan"))
        self.assertRedirects(self.client.get(self.url("scan")), self.url("uhid"), fetch_redirect_response=False)


class GuestFlowTests(KioskTestBase):
    def test_guest_flow_is_anonymous(self):
        self.identify_with_uhid()  # then change their mind
        response = self.client.post(
            self.url("guest"), {"clinic": "ent", "age_group": "31_45", "sex": "female", "action": "start"}
        )
        self.assertRedirects(response, self.url("question", number=1), fetch_redirect_response=False)
        page = self.client.get(self.url("question", number=1))
        self.assertNotContains(page, "123 4567 8901")

        self.answer_all()
        self.client.post(self.url("review"))
        saved = FeedbackResponse.objects.get()
        self.assertEqual(saved.identification_method, "guest")
        self.assertEqual(saved.uhid, "")
        self.assertIsNone(saved.patient)
        self.assertEqual((saved.clinic, saved.age_group, saved.sex), ("ENT", "31_45", "female"))

    def test_unknown_choices_are_ignored(self):
        self.client.post(self.url("guest"), {"clinic": "<script>", "age_group": "200", "action": "start"})
        self.assertEqual(self.draft()["guest"], {"clinic": "", "age_group": "", "sex": ""})

    def test_kiosk_clinic_list(self):
        self.kiosk.clinics = [{"en": "Ayush", "kn": "ಆಯುಷ್", "code": "ayush"}]
        self.kiosk.save()
        response = self.client.get(self.url("guest"))
        self.assertContains(response, "Ayush")
        self.assertNotContains(response, "General Medicine")


class GuardTests(KioskTestBase):
    def test_questions_need_identification(self):
        response = self.client.get(self.url("question", number=1))
        self.assertRedirects(response, self.url("start"), fetch_redirect_response=False)

    def test_cannot_skip_ahead(self):
        self.identify_with_uhid()
        self.client.post(self.url("question", number=1), {"rating": 5})
        response = self.client.get(self.url("question", number=6))
        self.assertRedirects(response, self.url("question", number=2), fetch_redirect_response=False)

    def test_comments_and_review_need_every_rating(self):
        self.identify_with_uhid()
        self.client.post(self.url("question", number=1), {"rating": 5})
        for name in ("comments", "review"):
            response = self.client.get(self.url(name))
            self.assertRedirects(response, self.url("question", number=2), fetch_redirect_response=False)

    def test_invalid_rating_is_ignored(self):
        self.identify_with_uhid()
        self.client.post(self.url("question", number=1), {"rating": "9"})
        self.assertEqual(self.draft()["ratings"], {})

    def test_change_from_review_returns_to_review(self):
        self.identify_with_uhid()
        self.answer_all()
        response = self.client.post(self.url("question", number=4), {"rating": 1, "return_to": "review"})
        self.assertRedirects(response, self.url("review"), fetch_redirect_response=False)

    def test_abandoned_draft_expires(self):
        self.identify_with_uhid()
        session = self.client.session
        key = f"patient_feedback:{self.kiosk.external_id}"
        draft = session[key]
        draft["last_activity"] = time.time() - 3600
        session[key] = draft
        session.save()
        response = self.client.get(self.url("question", number=1))
        self.assertRedirects(response, self.url("start"), fetch_redirect_response=False)
        self.assertIsNone(self.draft()["method"])

    def test_reset_clears_answers(self):
        self.identify_with_uhid()
        self.client.post(self.url("question", number=1), {"rating": 5})
        self.client.get(self.url("reset"))
        self.assertEqual(self.draft()["ratings"], {})


class LanguageTests(KioskTestBase):
    def test_switch_language_by_link(self):
        start = self.url("start")
        response = self.client.get(self.url("language", code="kn"), {"next": start})
        self.assertRedirects(response, start, fetch_redirect_response=False)
        page = self.client.get(start)
        self.assertContains(page, 'lang="kn"')
        self.assertContains(page, "ಇಂದಿನ ನಿಮ್ಮ ಭೇಟಿಯ ಬಗ್ಗೆ ತಿಳಿಸಿ.")

    def test_language_link_rejects_outside_redirects(self):
        response = self.client.get(self.url("language", code="kn"), {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], self.url("start"))

    def test_switching_on_comments_keeps_typed_text(self):
        self.identify_with_uhid()
        self.answer_all()
        response = self.client.post(self.url("comments"), {"_lang": "kn", "improvement": "More fans"})
        self.assertRedirects(response, self.url("comments"), fetch_redirect_response=False)
        page = self.client.get(self.url("comments"))
        self.assertContains(page, "More fans")
        self.assertContains(page, "ಕೊನೆಯ ನಾಲ್ಕು")

    def test_idle_reset_returns_to_default_language(self):
        self.client.get(self.url("language", code="kn"))
        self.client.get(self.url("reset"), {"idle": "1"})
        self.assertEqual(self.draft()["lang"], "en")

    def test_kannada_default(self):
        self.kiosk.default_language = "kn"
        self.kiosk.save()
        self.assertContains(self.client.get(self.url("start")), 'lang="kn"')


class PatientLinkTests(KioskTestBase):
    def setUp(self):
        super().setUp()
        self.config = PatientIdentifierConfig.objects.create(
            facility=self.facility,
            status="active",
            config={
                "system": "uhid",
                "display": "UHID",
                "required": False,
                "unique": True,
                "regex": "",
                "use": "usual",
            },
        )
        self.patient = self.create_patient()
        PatientIdentifier.objects.create(patient=self.patient, config=self.config, value=UHID, facility=self.facility)
        self.kiosk.patient_identifier_config = self.config
        self.kiosk.save()

    def test_links_patient_and_recent_encounter(self):
        organization = self.create_facility_organization(self.facility)
        encounter = self.create_encounter(self.patient, self.facility, organization)
        self.identify_with_uhid()
        self.answer_all()
        self.client.post(self.url("review"))
        saved = FeedbackResponse.objects.get()
        self.assertEqual(saved.patient, self.patient)
        self.assertEqual(saved.encounter, encounter)

    def test_old_encounter_is_not_linked(self):
        organization = self.create_facility_organization(self.facility)
        encounter = self.create_encounter(self.patient, self.facility, organization)
        type(encounter).objects.filter(pk=encounter.pk).update(created_date=timezone.now() - timedelta(days=5))
        self.identify_with_uhid()
        self.answer_all()
        self.client.post(self.url("review"))
        self.assertIsNone(FeedbackResponse.objects.get().encounter)

    def test_unknown_uhid_allowed_by_default(self):
        response = self.identify_with_uhid("99999999999")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.draft()["patient_id"])

    def test_unknown_uhid_rejected_when_required(self):
        self.kiosk.require_registered_uhid = True
        self.kiosk.save()
        response = self.identify_with_uhid("99999999999")
        self.assertContains(response, "find a patient with this UHID")


class ReferenceNumberTests(KioskTestBase):
    def test_collision_is_retried(self):
        self.identify_with_uhid()
        self.answer_all()
        self.client.post(self.url("review"))
        taken = FeedbackResponse.objects.get().reference_number

        self.identify_with_uhid()
        self.answer_all()
        with mock.patch("patient_feedback.services._reference_number", side_effect=[taken, "OPD-20261118-1111"]):
            self.client.post(self.url("review"))
        self.assertEqual(
            sorted(FeedbackResponse.objects.values_list("reference_number", flat=True)),
            sorted([taken, "OPD-20261118-1111"]),
        )
