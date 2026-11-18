import time
from datetime import timedelta
from unittest import mock

from care.emr.models.patient import PatientIdentifier, PatientIdentifierConfig
from care.utils.tests.base import CareAPITestBase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from patient_feedback import kiosk_auth
from patient_feedback.models import FeedbackForm, FeedbackKiosk, FeedbackQuestion, FeedbackSubmission, ScanMode
from patient_feedback.questionnaire import FormSpec
from patient_feedback.tests import PLAIN_STATIC_STORAGES
from patient_feedback.views import FORM_PAGES

UHID = "12345678901"


@override_settings(STORAGES=PLAIN_STATIC_STORAGES)
class KioskTestBase(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.facility = self.create_facility(user=self.user, name="District Hospital, Mysuru")
        self.kiosk = FeedbackKiosk.objects.create(facility=self.facility, name="OPD block")
        # Seeded by the 0003 data migration
        self.opd = FeedbackForm.objects.get(code="opd", facility__isnull=True)
        self.ipd = FeedbackForm.objects.get(code="ipd", facility__isnull=True)
        self.form_code = "opd"  # form used by url() for a form's pages
        self.open_kiosk()

    # ── helpers ─────────────────────────────────────────────────────
    def url(self, name, kiosk=None, **kwargs):
        kiosk = kiosk or self.kiosk
        if name in FORM_PAGES and "form" not in kwargs:
            kwargs["form"] = self.form_code
        return reverse(f"patient_feedback:{name}", kwargs={"facility_id": kiosk.facility.external_id, **kwargs})

    def identify_url(self, via="flow", form=None):
        return f"{self.url('identify', form=form or self.form_code)}?from={via}"

    def open_kiosk(self, kiosk=None):
        kiosk = kiosk or self.kiosk
        response = self.client.get(self.url("start", kiosk), {"key": kiosk.access_key})
        self.assertEqual(response.status_code, 302)
        return response

    def draft(self, kiosk=None):
        return self.client.session.get(f"patient_feedback:{(kiosk or self.kiosk).external_id}") or {}

    def choose(self, code="opd"):
        """Pick a form on the chooser, as a patient would."""
        self.form_code = code
        self.assertEqual(self.client.get(self.identify_url("start")).status_code, 200)

    def identify_with_uhid(self, uhid=UHID):
        return self.client.post(self.url("uhid"), {"uhid": uhid, "action": "continue"})

    def as_guest(self):
        return self.client.get(self.url("guest"))

    def fill_details(self, **answers):
        return self.client.post(self.url("details"), {"action": "next", **answers})

    def rating_count(self, form, method="manual"):
        return len(FormSpec(form, method).ratings)

    def q_url(self, number, from_review=False):
        url = f"{self.url('questions')}?q={number}"
        return f"{url}&from=review" if from_review else url

    def rating_keys(self, form, method="manual"):
        return [q.key for q in FormSpec(form, method).ratings]

    def answer_all(self, form, value=5, method="manual"):
        """What kiosk.js sends at the end: every answer in its hidden field."""
        data = {f"rating_{key}": value for key in self.rating_keys(form, method)}
        response = self.client.post(self.url("questions"), {**data, "action": "done"})
        self.assertEqual(response.status_code, 302)
        return response

    def answer(self, key, value, **extra):
        """What an answer button sends without JavaScript."""
        return self.client.post(self.url("questions"), {"answer": f"{key}:{value}", **extra})

    def finish_open(self, **answers):
        return self.client.post(self.url("comments"), {"action": "review", **answers})

    def opd_to_review(self, value=5):
        self.choose("opd")
        self.identify_with_uhid()
        self.fill_details(clinic="ent")
        self.answer_all(self.opd, value)
        self.finish_open()


class KioskAccessTests(KioskTestBase):
    def test_kiosk_lives_under_the_facility(self):
        self.assertEqual(self.url("start"), f"/facility/{self.facility.external_id}/patient_feedback/")

    def test_key_sets_cookie_and_strips_key_from_url(self):
        self.client.cookies.clear()
        response = self.open_kiosk()
        self.assertEqual(response["Location"], self.url("start"))
        cookie = response.cookies[kiosk_auth.cookie_name(self.facility.external_id)]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], self.url("start"))
        self.assertEqual(self.client.get(self.url("start")).status_code, 200)

    def test_browser_without_cookie_is_blocked(self):
        self.client.cookies.clear()
        response = self.client.get(self.url("start"))
        self.assertContains(response, "isn't set up as a feedback kiosk", status_code=403)

    def test_wrong_key_is_blocked(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get(self.url("start"), {"key": "not-the-key"}).status_code, 403)

    def test_regenerated_key_revokes_cookie(self):
        self.kiosk.regenerate_access_key()
        self.assertEqual(self.client.get(self.url("start")).status_code, 403)

    def test_unknown_facility_is_blocked(self):
        response = self.client.get(
            reverse("patient_feedback:start", kwargs={"facility_id": "00000000-0000-0000-0000-000000000000"})
        )
        self.assertEqual(response.status_code, 403)

    def test_key_from_another_facility_is_rejected(self):
        other = FeedbackKiosk.objects.create(facility=self.create_facility(user=self.user), name="Elsewhere")
        self.assertEqual(self.client.get(self.url("start"), {"key": other.access_key}).status_code, 403)

    def test_cookie_for_one_facility_does_not_open_another(self):
        other = FeedbackKiosk.objects.create(facility=self.create_facility(user=self.user), name="Elsewhere")
        self.assertEqual(self.client.get(self.url("start", other)).status_code, 403)

    def test_second_kiosk_key_switches_the_browser(self):
        other = FeedbackKiosk.objects.create(facility=self.facility, name="Ward", default_language="kn")
        self.open_kiosk(other)
        response = self.client.get(self.url("start"))
        self.assertContains(response, 'lang="kn"')
        self.assertEqual(response.context["kiosk"], other)

    def test_inactive_kiosk(self):
        self.kiosk.is_active = False
        self.kiosk.save()
        self.assertContains(self.client.get(self.url("start")), "switched off", status_code=403)

    def test_last_seen_is_recorded(self):
        self.client.get(self.url("start"))
        self.kiosk.refresh_from_db()
        self.assertIsNotNone(self.kiosk.last_seen_at)


class DefaultFormTests(KioskTestBase):
    def test_nqas_forms_are_seeded(self):
        self.assertEqual((self.opd.patient_type, self.ipd.patient_type), ("op", "ip"))
        guest_opd, guest_ipd = FormSpec(self.opd, "guest"), FormSpec(self.ipd, "guest")
        self.assertEqual(len(guest_opd.ratings), 10)
        self.assertEqual(len(guest_ipd.ratings), 20)
        self.assertEqual([q.key for q in guest_opd.details], ["clinic", "age_group", "sex"])
        self.assertEqual([q.key for q in guest_ipd.details], ["ward", "date_of_admission", "age_group", "sex"])
        self.assertEqual(
            [q.key for q in guest_ipd.open_questions],
            ["would_return", "improvement", "reason_for_choosing", "suggestions"],
        )
        # Age and sex are only asked of guests
        self.assertEqual([q.key for q in FormSpec(self.opd, "manual").details], ["clinic"])

    def test_waiting_time_uses_its_own_labels(self):
        question = self.ipd.questions.get(key="admission_wait")
        self.assertEqual(question.options[0]["en"], "More than 30 mins")
        self.assertEqual(question.options[4]["en"], "Immediate")


class FormChoiceTests(KioskTestBase):
    def test_start_offers_op_and_ip(self):
        response = self.client.get(self.url("start"))
        self.assertContains(response, "OPD feedback")
        self.assertContains(response, "Inpatient feedback")
        self.assertContains(response, self.identify_url("start", form="ipd"))

    def test_kiosk_with_one_form_skips_the_chooser(self):
        self.kiosk.forms.set([self.ipd])
        self.assertRedirects(
            self.client.get(self.url("start")), self.url("identify", form="ipd"), fetch_redirect_response=False
        )
        self.assertContains(self.client.get(self.url("identify", form="ipd")), "20 short questions")

    def test_facility_form_replaces_shared_form_with_same_code(self):
        FeedbackForm.objects.create(
            facility=self.facility, code="opd", patient_type="op", title={"en": "Mysuru OPD survey"}
        )
        response = self.client.get(self.url("start"))
        self.assertContains(response, "Mysuru OPD survey")
        self.assertNotContains(response, "OPD feedback")

    def test_no_active_forms(self):
        FeedbackForm.objects.update(is_active=False)
        self.assertContains(self.client.get(self.url("start")), "No feedback forms", status_code=403)

    def test_switching_form_drops_answers(self):
        self.choose("opd")
        self.identify_with_uhid()
        self.choose("ipd")
        self.assertIsNone(self.draft()["method"])
        self.assertEqual(self.draft()["answers"], {})

    def test_steps_need_a_form(self):
        self.assertRedirects(
            self.client.get(self.url("identify", form="nope")), self.url("start"), fetch_redirect_response=False
        )


class FormUrlTests(KioskTestBase):
    def test_each_form_has_its_own_url(self):
        self.assertEqual(
            self.url("identify", form="ipd"), f"/facility/{self.facility.external_id}/patient_feedback/ipd/"
        )
        self.assertEqual(self.url("questions", form="ipd"), f"{self.url('identify', form='ipd')}questions/")

    def test_launching_on_a_form_url_pins_the_kiosk(self):
        self.form_code = "ipd"
        page = self.client.get(self.url("identify"))
        self.assertContains(page, "Step 1")
        self.assertNotContains(page, f'href="{self.url("start")}"')  # no way back to the chooser
        # Idle reset and "Submit another response" come back to this form
        self.assertRedirects(
            self.client.get(self.url("reset"), {"idle": "1"}), self.url("identify"), fetch_redirect_response=False
        )
        self.as_guest()
        self.fill_details()
        self.answer_all(self.ipd, method="guest")
        self.finish_open()
        self.client.post(self.url("review"))
        self.assertRedirects(self.client.get(self.url("reset")), self.url("identify"), fetch_redirect_response=False)

    def test_chooser_kiosk_returns_to_the_chooser(self):
        self.client.get(self.url("start"))
        page = self.client.get(self.identify_url("start", form="ipd"))
        self.assertContains(page, "Step 2")
        self.assertContains(page, f'href="{self.url("start")}"')
        self.assertRedirects(self.client.get(self.url("reset")), self.url("start"), fetch_redirect_response=False)

    def test_inner_links_back_to_identify_do_not_pin(self):
        self.client.get(self.url("start"))
        self.choose("opd")
        self.client.get(self.identify_url())  # e.g. Back from the details screen
        self.assertRedirects(self.client.get(self.url("reset")), self.url("start"), fetch_redirect_response=False)

    def test_key_on_a_form_url_stays_on_that_form(self):
        self.client.cookies.clear()
        form_url = self.url("identify", form="ipd")
        response = self.client.get(form_url, {"key": self.kiosk.access_key})
        self.assertRedirects(response, form_url, fetch_redirect_response=False)
        self.assertEqual(self.client.get(form_url).status_code, 200)

    def test_form_not_offered_on_this_kiosk(self):
        self.kiosk.forms.set([self.opd])
        self.assertRedirects(
            self.client.get(self.url("identify", form="ipd")), self.url("start"), fetch_redirect_response=False
        )


class OpdFlowTests(KioskTestBase):
    def test_full_uhid_flow_stores_a_snapshot(self):
        self.choose("opd")
        self.assertContains(self.client.get(self.identify_url()), "10 short questions")
        self.assertRedirects(
            self.identify_with_uhid("123 4567 8901"), self.url("details"), fetch_redirect_response=False
        )

        details = self.client.get(self.url("details"))
        self.assertContains(details, "Clinic visited")
        self.assertNotContains(details, "Age group")  # guests only
        self.assertRedirects(self.fill_details(clinic="ent"), self.q_url(1), fetch_redirect_response=False)

        self.answer("information_signage", 4)
        page = self.client.get(self.url("questions"), {"q": 2})
        self.assertEqual(page.context["start_index"], 1)
        self.assertContains(page, "Question 2 of 10")
        self.assertContains(page, "More than 30 mins")
        self.assertContains(page, "123 4567 8901")  # UHID pill

        self.answer_all(self.opd, 4)
        self.answer("staff_behaviour", 0)  # "No comments"
        response = self.finish_open(
            would_return="yes", would_return__comment="Kind staff", improvement="Shorter queues"
        )
        self.assertRedirects(response, self.url("review"), fetch_redirect_response=False)

        review = self.client.get(self.url("review"))
        self.assertContains(review, "ENT")
        self.assertContains(review, "No comments")
        self.assertContains(review, "Shorter queues")

        self.assertRedirects(self.client.post(self.url("review")), self.url("done"), fetch_redirect_response=False)
        saved = FeedbackSubmission.objects.get()
        self.assertEqual((saved.form_code, saved.patient_type), ("opd", "op"))
        self.assertEqual(saved.facility_external_id, self.facility.external_id)
        self.assertEqual(saved.facility_name, "District Hospital, Mysuru")
        self.assertEqual(saved.kiosk_external_id, self.kiosk.external_id)
        self.assertEqual((saved.identification_method, saved.uhid), ("manual", UHID))
        self.assertEqual(len(saved.ratings), 10)
        self.assertEqual(saved.ratings["staff_behaviour"], 0)
        self.assertEqual(str(saved.average_rating), "4.00")  # "No comments" isn't averaged
        answers = {a["key"]: a for a in saved.answers}
        self.assertEqual(answers["clinic"]["display"], "ENT")
        self.assertEqual(answers["registration_wait"]["display"], "Within 5 mins")
        self.assertEqual((answers["would_return"]["value"], answers["would_return"]["comment"]), (True, "Kind staff"))
        self.assertEqual(answers["improvement"]["value"], "Shorter queues")
        self.assertNotIn("age_group", answers)
        self.assertRegex(saved.reference_number, r"^OPD-\d{8}-\d{4}$")

        self.assertContains(self.client.get(self.url("done")), saved.reference_number)
        # The draft is gone: the next patient starts from scratch.
        self.assertRedirects(self.client.get(self.url("review")), self.identify_url(), fetch_redirect_response=False)

    def test_double_submit_shows_reference_again(self):
        self.opd_to_review()
        self.client.post(self.url("review"))
        self.assertRedirects(self.client.post(self.url("review")), self.url("done"), fetch_redirect_response=False)
        self.assertEqual(FeedbackSubmission.objects.count(), 1)

    def test_snapshot_survives_later_form_edits(self):
        self.opd_to_review()
        self.client.post(self.url("review"))
        question = self.opd.questions.get(key="staff_behaviour")
        question.text = {"en": "Reworded"}
        question.save()
        answer = next(a for a in FeedbackSubmission.objects.get().answers if a["key"] == "staff_behaviour")
        self.assertEqual(answer["question"], "Behaviour and attitude of the hospital staff")

    def test_submission_table_has_no_relations(self):
        self.assertFalse([f.name for f in FeedbackSubmission._meta.get_fields() if f.is_relation])


class IpdFlowTests(KioskTestBase):
    def test_guest_inpatient_flow(self):
        self.choose("ipd")
        self.identify_with_uhid()  # then change their mind
        self.assertRedirects(self.as_guest(), self.url("details"), fetch_redirect_response=False)
        details = self.client.get(self.url("details"))
        for text in ("Ward", "Date of admission", "Age group", "Sex"):
            self.assertContains(details, text)

        admitted = (timezone.localdate() - timedelta(days=3)).isoformat()
        self.fill_details(ward="icu", date_of_admission=admitted, age_group="46_60", sex="female")
        self.assertContains(self.client.get(self.url("questions")), "Question 20 of 20")
        self.answer_all(self.ipd, 3, method="guest")
        self.finish_open(would_return="no")
        self.client.post(self.url("review"))

        saved = FeedbackSubmission.objects.get()
        self.assertEqual((saved.form_code, saved.patient_type, saved.uhid), ("ipd", "ip", ""))
        self.assertRegex(saved.reference_number, r"^IPD-\d{8}-\d{4}$")
        self.assertIsNone(saved.patient_external_id)
        self.assertEqual(len(saved.ratings), 20)
        answers = {a["key"]: a for a in saved.answers}
        self.assertEqual(answers["ward"]["display"], "ICU / HDU")
        self.assertEqual(answers["date_of_admission"]["value"], admitted)
        self.assertEqual(answers["sex"]["value"], "female")
        self.assertIs(answers["would_return"]["value"], False)

    def test_future_admission_date_is_ignored(self):
        self.choose("ipd")
        self.as_guest()
        self.fill_details(date_of_admission=(timezone.localdate() + timedelta(days=2)).isoformat())
        self.assertNotIn("date_of_admission", self.draft()["answers"])

    def test_unknown_choice_is_ignored(self):
        self.choose("ipd")
        self.as_guest()
        self.fill_details(ward="<script>", age_group="200")
        self.assertEqual(self.draft()["answers"], {})


class ConfigurationTests(KioskTestBase):
    def test_required_detail_must_be_answered(self):
        self.opd.questions.filter(key="clinic").update(required=True)
        self.choose("opd")
        self.identify_with_uhid()
        self.assertContains(self.fill_details(), "This question needs an answer.")
        self.assertRedirects(self.fill_details(clinic="dental"), self.q_url(1), fetch_redirect_response=False)

    def test_inactive_question_is_not_asked(self):
        self.opd.questions.filter(key="overall_satisfaction").update(is_active=False)
        self.choose("opd")
        self.identify_with_uhid()
        self.fill_details()
        page = self.client.get(self.url("questions"))
        self.assertContains(page, "Question 9 of 9")
        self.assertNotContains(page, "Question 10 of")

    def test_added_question_is_asked_and_stored(self):
        FeedbackQuestion.objects.create(
            form=self.opd, key="parking", order=999, type="text", text={"en": "How was parking?"}
        )
        self.opd_to_review()
        self.assertContains(self.client.get(self.url("comments")), "How was parking?")
        self.finish_open(parking="Hard to find a spot")
        self.client.post(self.url("review"))
        answers = {a["key"]: a for a in FeedbackSubmission.objects.get().answers}
        self.assertEqual(answers["parking"]["value"], "Hard to find a spot")

    def test_rating_without_no_comment_option(self):
        self.opd.questions.filter(key="information_signage").update(allow_no_comment=False)
        self.choose("opd")
        self.identify_with_uhid()
        self.fill_details()
        questions = self.client.get(self.url("questions")).context["questions"]
        self.assertNotIn(0, [option["value"] for option in questions[0]["options"]])
        self.assertIn(0, [option["value"] for option in questions[1]["options"]])
        self.answer("information_signage", 0)
        self.assertNotIn("information_signage", self.draft()["answers"])

    def test_form_without_details_or_open_questions(self):
        form = FeedbackForm.objects.create(code="quick", patient_type="op", title={"en": "Quick"})
        FeedbackQuestion.objects.create(form=form, key="overall", type="rating", text={"en": "Overall?"})
        self.kiosk.forms.set([form])
        self.form_code = "quick"
        self.assertRedirects(self.identify_with_uhid(), self.q_url(1), fetch_redirect_response=False)
        response = self.answer("overall", 5)
        self.assertRedirects(response, self.url("review"), fetch_redirect_response=False)


class OnePageQuestionTests(KioskTestBase):
    def setUp(self):
        super().setUp()
        self.choose("opd")
        self.identify_with_uhid()
        self.fill_details()

    def test_every_question_is_on_one_page(self):
        page = self.client.get(self.url("questions"))
        self.assertEqual(len(page.context["questions"]), 10)
        self.assertContains(page, 'class="qcard is-active"', count=1)
        self.assertContains(page, 'name="rating_overall_satisfaction"')

    def test_no_javascript_answers_move_to_the_next_card(self):
        self.assertRedirects(self.answer("information_signage", 5), self.q_url(2), fetch_redirect_response=False)
        response = self.client.post(self.url("questions"), {"nav": "back:1"})
        self.assertRedirects(response, self.q_url(1), fetch_redirect_response=False)
        response = self.client.post(self.url("questions"), {"nav": "next:0"})
        self.assertRedirects(response, self.q_url(2), fetch_redirect_response=False)
        response = self.client.post(self.url("questions"), {"nav": "back:0"})
        self.assertRedirects(response, self.url("details"), fetch_redirect_response=False)

    def test_last_answer_moves_on_to_open_questions(self):
        keys = self.rating_keys(self.opd)
        data = {f"rating_{key}": 4 for key in keys[:-1]}
        response = self.client.post(self.url("questions"), {**data, "answer": f"{keys[-1]}:5"})
        self.assertRedirects(response, self.url("comments"), fetch_redirect_response=False)

    def test_autosave_keeps_answers_without_navigating(self):
        response = self.client.post(
            self.url("questions"), {"rating_information_signage": 3, "rating_registration_wait": 0, "autosave": "1"}
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.draft()["answers"], {"information_signage": 3, "registration_wait": 0})
        self.assertEqual(self.client.get(self.url("questions")).context["start_index"], 2)

    def test_incomplete_final_submit_returns_to_first_gap(self):
        response = self.client.post(self.url("questions"), {"rating_information_signage": 3, "action": "done"})
        self.assertRedirects(response, self.q_url(2), fetch_redirect_response=False)

    def test_switching_language_keeps_position(self):
        response = self.client.post(
            self.url("questions"), {"rating_information_signage": 3, "current": 1, "_lang": "kn"}
        )
        self.assertRedirects(response, self.q_url(2), fetch_redirect_response=False)
        self.assertEqual(self.draft()["lang"], "kn")

    def test_invalid_values_are_ignored(self):
        self.client.post(self.url("questions"), {"rating_information_signage": 9, "answer": "nope:5", "autosave": "1"})
        self.assertEqual(self.draft()["answers"], {})


class GuardTests(KioskTestBase):
    def test_questions_need_identification(self):
        self.choose("opd")
        self.assertRedirects(self.client.get(self.url("questions")), self.identify_url(), fetch_redirect_response=False)

    def test_questions_wait_for_details(self):
        self.choose("opd")
        self.identify_with_uhid()
        self.assertRedirects(self.client.get(self.url("questions")), self.url("details"), fetch_redirect_response=False)

    def test_cannot_skip_ahead(self):
        self.choose("opd")
        self.identify_with_uhid()
        self.fill_details()
        self.answer("information_signage", 5)
        # Asking for question 6 opens the first unanswered one instead
        self.assertEqual(self.client.get(self.url("questions"), {"q": 6}).context["start_index"], 1)

    def test_comments_and_review_need_every_rating(self):
        self.choose("opd")
        self.identify_with_uhid()
        self.fill_details()
        self.answer("information_signage", 5)
        for name in ("comments", "review"):
            self.assertRedirects(self.client.get(self.url(name)), self.q_url(2), fetch_redirect_response=False)

    def test_change_from_review_returns_to_review(self):
        self.opd_to_review()
        response = self.answer("waiting_area", 1, return_to="review")
        self.assertRedirects(response, self.url("review"), fetch_redirect_response=False)

    def test_abandoned_draft_expires(self):
        self.choose("opd")
        self.identify_with_uhid()
        session = self.client.session
        key = f"patient_feedback:{self.kiosk.external_id}"
        draft = session[key]
        draft["last_activity"] = time.time() - 3600
        session[key] = draft
        session.save()
        self.assertRedirects(self.client.get(self.url("details")), self.url("start"), fetch_redirect_response=False)
        self.assertIsNone(self.draft()["method"])

    def test_reset_clears_answers(self):
        self.choose("opd")
        self.identify_with_uhid()
        self.fill_details(clinic="ent")
        self.client.get(self.url("reset"))
        self.assertEqual(self.draft()["answers"], {})


class InputTests(KioskTestBase):
    def setUp(self):
        super().setUp()
        self.choose("opd")

    def test_short_uhid_shows_error(self):
        response = self.identify_with_uhid("12345")
        self.assertContains(response, "Enter all 11 digits of your UHID.")
        self.assertEqual(self.draft()["uhid_input"], "12345")

    def test_keypad_without_javascript(self):
        self.client.post(self.url("uhid"), {"uhid": "12", "key": "3"})
        self.assertEqual(self.draft()["uhid_input"], "123")
        self.client.post(self.url("uhid"), {"uhid": "123", "key": "back"})
        self.assertEqual(self.draft()["uhid_input"], "12")
        self.client.post(self.url("uhid"), {"uhid": "12", "key": "clear"})
        self.assertEqual(self.draft()["uhid_input"], "")
        self.client.post(self.url("uhid"), {"uhid": UHID, "key": "9"})
        self.assertEqual(self.draft()["uhid_input"], UHID)

    def test_scan_accepts_payload_with_other_characters(self):
        response = self.client.post(self.url("scan"), {"code": "UHID:123-4567-8901"})
        self.assertRedirects(response, self.url("details"), fetch_redirect_response=False)
        self.assertEqual(self.draft()["method"], "scan")

    def test_scan_rejects_payload_without_uhid(self):
        self.assertContains(self.client.post(self.url("scan"), {"code": "https://example.org/x"}), "read a UHID")

    def test_scan_disabled_kiosk_hides_scan_option(self):
        self.kiosk.scan_mode = ScanMode.DISABLED
        self.kiosk.save()
        self.assertNotContains(self.client.get(self.identify_url()), self.url("scan"))
        self.assertRedirects(self.client.get(self.url("scan")), self.url("uhid"), fetch_redirect_response=False)


class LanguageTests(KioskTestBase):
    def test_switch_language_by_link(self):
        start = self.url("start")
        self.assertRedirects(
            self.client.get(self.url("language", code="kn"), {"next": start}), start, fetch_redirect_response=False
        )
        page = self.client.get(start)
        self.assertContains(page, 'lang="kn"')
        self.assertContains(page, "ಒಳರೋಗಿ ಅಭಿಪ್ರಾಯ")

    def test_language_link_rejects_outside_redirects(self):
        response = self.client.get(self.url("language", code="kn"), {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], self.url("start"))

    def test_switching_on_comments_keeps_typed_text(self):
        self.opd_to_review()
        response = self.client.post(self.url("comments"), {"_lang": "kn", "improvement": "More fans"})
        self.assertRedirects(response, self.url("comments"), fetch_redirect_response=False)
        page = self.client.get(self.url("comments"))
        self.assertContains(page, "More fans")
        self.assertContains(page, "ಕೊನೆಯ 4")

    def test_idle_reset_returns_to_default_language(self):
        self.client.get(self.url("language", code="kn"))
        self.client.get(self.url("reset"), {"idle": "1"})
        self.assertEqual(self.draft()["lang"], "en")


class PatientRecordTests(KioskTestBase):
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
        self.organization = self.create_facility_organization(self.facility)

    def submit(self, code):
        self.choose(code)
        self.identify_with_uhid()
        self.fill_details()
        self.answer_all(self.opd if code == "opd" else self.ipd)
        self.finish_open()
        self.client.post(self.url("review"))
        return FeedbackSubmission.objects.get()

    def test_records_patient_and_recent_encounter_as_plain_ids(self):
        encounter = self.create_encounter(self.patient, self.facility, self.organization)
        saved = self.submit("opd")
        self.assertEqual(saved.patient_external_id, self.patient.external_id)
        self.assertEqual(saved.encounter_external_id, encounter.external_id)

    def test_old_encounter_is_not_recorded_for_op(self):
        encounter = self.create_encounter(self.patient, self.facility, self.organization)
        type(encounter).objects.filter(pk=encounter.pk).update(created_date=timezone.now() - timedelta(days=5))
        self.assertIsNone(self.submit("opd").encounter_external_id)

    def test_inpatient_form_looks_back_further(self):
        encounter = self.create_encounter(self.patient, self.facility, self.organization, encounter_class="imp")
        type(encounter).objects.filter(pk=encounter.pk).update(created_date=timezone.now() - timedelta(days=5))
        self.assertEqual(self.submit("ipd").encounter_external_id, encounter.external_id)

    def test_unknown_uhid_rejected_when_required(self):
        self.kiosk.require_registered_uhid = True
        self.kiosk.save()
        self.choose("opd")
        self.assertContains(self.identify_with_uhid("99999999999"), "find a patient with this UHID")


class ReferenceNumberTests(KioskTestBase):
    def test_collision_is_retried(self):
        self.opd_to_review()
        self.client.post(self.url("review"))
        taken = FeedbackSubmission.objects.get().reference_number

        self.opd_to_review()
        with mock.patch("patient_feedback.services._reference_number", side_effect=[taken, "OPD-20261118-1111"]):
            self.client.post(self.url("review"))
        self.assertEqual(
            sorted(FeedbackSubmission.objects.values_list("reference_number", flat=True)),
            sorted([taken, "OPD-20261118-1111"]),
        )
