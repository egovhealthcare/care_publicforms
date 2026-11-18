from datetime import timedelta

from care.utils.tests.base import CareAPITestBase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from patient_feedback.admin import FeedbackFormForm, QuestionForm
from patient_feedback.models import FeedbackForm, FeedbackSubmission
from patient_feedback.tests import PLAIN_STATIC_STORAGES


def make_submission(facility, reference, form_code, answers, uhid="", **extra):
    submission = FeedbackSubmission.objects.create(
        reference_number=reference,
        facility_external_id=facility.external_id,
        form_code=form_code,
        patient_type="ip" if form_code == "ipd" else "op",
        language="en",
        uhid=uhid,
        answers=answers,
    )
    if "submitted_at" in extra:  # auto_now_add ignores a value given on create
        FeedbackSubmission.objects.filter(pk=submission.pk).update(submitted_at=extra["submitted_at"])
    return submission


class FeedbackApiTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.facility = self.create_facility(user=self.create_user())
        self.superuser = self.create_super_user()
        make_submission(
            self.facility,
            "OPD-1",
            "opd",
            {
                "clinic": "ent",
                "information_signage": 5,
                "registration_wait": 2,
                "overall_satisfaction": 4,
                "would_return": True,
            },
            uhid="12345678901",
        )
        make_submission(
            self.facility,
            "OPD-2",
            "opd",
            {
                "clinic": "ent",
                "information_signage": 3,
                "registration_wait": 0,
                "overall_satisfaction": 3,
                "would_return": False,
            },
        )
        make_submission(self.facility, "IPD-1", "ipd", {"ward_cleanliness": 2, "diet": 1, "overall_satisfaction": 5})
        make_submission(self.facility, "IPD-OLD", "ipd", {"diet": 5}, submitted_at=timezone.now() - timedelta(days=40))
        make_submission(self.create_facility(user=self.create_user()), "ELSEWHERE", "opd", {"overall_satisfaction": 1})

    def url(self, name):
        return reverse(f"patient_feedback_api:{name}", kwargs={"facility_external_id": self.facility.external_id})

    def test_requires_login(self):
        self.assertIn(self.client.get(self.url("facility-summary")).status_code, (401, 403))

    def test_user_without_facility_access_is_denied(self):
        self.client.force_authenticate(self.create_user())
        self.assertEqual(self.client.get(self.url("facility-responses")).status_code, 403)
        self.assertEqual(self.client.get(self.url("facility-summary")).status_code, 403)

    def test_list_returns_the_stored_fields_and_filters(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get(self.url("facility-responses"))
        self.assertEqual(response.data["count"], 4)  # other facility excluded
        self.assertEqual(
            set(response.data["results"][0]),
            {"id", "reference_number", "submitted_at", "form_code", "patient_type", "language", "uhid", "answers"},
        )
        ip = self.client.get(self.url("facility-responses"), {"patient_type": "ip"})
        self.assertEqual({r["reference_number"] for r in ip.data["results"]}, {"IPD-1", "IPD-OLD"})
        opd = self.client.get(self.url("facility-responses"), {"form": "opd"})
        self.assertEqual(opd.data["results"][0]["answers"]["clinic"], "ent")

    def test_invalid_filters(self):
        self.client.force_authenticate(self.superuser)
        for params in ({"submitted_after": "x"}, {"submitted_before": "2026-13-01"}, {"patient_type": "er"}):
            self.assertEqual(self.client.get(self.url("facility-responses"), params).status_code, 400)

    def test_summary_per_form_with_lowest_attributes(self):
        self.client.force_authenticate(self.superuser)
        since = (timezone.localdate() - timedelta(days=7)).isoformat()
        data = self.client.get(self.url("facility-summary"), {"submitted_after": since}).data
        forms = {f["form"]: f for f in data["forms"]}
        opd = forms["opd"]
        self.assertEqual((opd["total"], opd["with_uhid"], opd["patient_type"]), (2, 1, "op"))
        ratings = {q["key"]: q for q in opd["ratings"]}
        self.assertEqual(ratings["registration_wait"]["average"], 2.0)  # "No comments" (0) isn't averaged
        self.assertEqual(ratings["registration_wait"]["distribution"]["0"], 1)
        self.assertEqual(ratings["registration_wait"]["text"]["en"], "Waiting time at the registration counter")
        self.assertIsNone(ratings["staff_behaviour"]["average"])
        self.assertEqual(opd["lowest"], ["registration_wait", "overall_satisfaction"])
        self.assertEqual(opd["average_rating"], round((5 + 2 + 4 + 3 + 3) / 5, 2))
        others = {q["key"]: q["counts"] for q in opd["other_questions"]}
        self.assertEqual(others["would_return"], {"yes": 1, "no": 1})
        self.assertEqual(others["clinic"], {"ent": 2})
        self.assertEqual(forms["ipd"]["lowest"], ["diet", "ward_cleanliness"])

    def test_summary_for_ip_only(self):
        self.client.force_authenticate(self.superuser)
        data = self.client.get(self.url("facility-summary"), {"patient_type": "ip"}).data
        self.assertEqual([(f["form"], f["total"]) for f in data["forms"]], [("ipd", 2)])

    def test_health(self):
        self.assertEqual(self.client.get(reverse("patient_feedback_api:health")).status_code, 200)


@override_settings(STORAGES=PLAIN_STATIC_STORAGES)
class AdminTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.superuser = self.create_super_user(is_staff=True)
        self.facility = self.create_facility(user=self.superuser, name="District Hospital, Mysuru")
        self.opd = FeedbackForm.objects.get(code="opd", facility__isnull=True)
        self.client.force_login(self.superuser)

    def test_form_page_shows_a_box_per_language_and_the_page_link(self):
        response = self.client.get(reverse("admin:patient_feedback_feedbackform_change", args=[self.opd.pk]))
        self.assertContains(response, "Title (English)")
        self.assertContains(response, "Title (Kannada)")
        self.assertContains(response, "Question (Kannada)")
        self.assertContains(response, "ಒಪಿಡಿ ಅಭಿಪ್ರಾಯ")
        self.assertContains(response, escape("/facility/<facility-id>/patient_feedback/opd/"))

    def test_facility_form_shows_its_full_link(self):
        own = FeedbackForm.objects.create(facility=self.facility, code="opd", patient_type="op", title={"en": "Ours"})
        response = self.client.get(reverse("admin:patient_feedback_feedbackform_change", args=[own.pk]))
        self.assertContains(response, f"http://testserver/facility/{self.facility.external_id}/patient_feedback/opd/")

    def test_localized_question_form_packs_languages(self):
        form = QuestionForm(
            data={
                "form": self.opd.pk,
                "key": "parking",
                "order": 5,
                "type": "choice",
                "text__en": "Where did you park?",
                "text__kn": "",
                "options": '[{"value": "inside", "en": "Inside the campus"}]',
                "audience": "all",
                "is_active": True,
                "allow_no_comment": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        question = form.save()
        self.assertEqual(question.text, {"en": "Where did you park?"})
        self.assertEqual(question.short_text, {})

    def test_question_validation(self):
        base = {"form": self.opd.pk, "order": 5, "text__en": "Q?", "audience": "all", "is_active": True}
        bad_choice = QuestionForm(data={**base, "key": "x_choice", "type": "choice", "options": "[]"})
        self.assertIn("options", bad_choice.errors)
        bad_rating = QuestionForm(data={**base, "key": "x_rating", "type": "rating", "options": '[{"en": "a"}]'})
        self.assertIn("options", bad_rating.errors)
        bad_key = QuestionForm(data={**base, "key": "Bad Key", "type": "text", "options": "[]"})
        self.assertIn("key", bad_key.errors)
        reserved = QuestionForm(data={**base, "key": "why__comment", "type": "text", "options": "[]"})
        self.assertIn("key", reserved.errors)
        duplicate = QuestionForm(data={**base, "key": "clinic", "type": "text", "options": "[]"})
        self.assertFalse(duplicate.is_valid())
        no_english = FeedbackFormForm(data={"code": "x", "patient_type": "op", "title__en": "", "order": 0})
        self.assertIn("title__en", no_english.errors)
        taken = FeedbackFormForm(data={"code": "opd", "patient_type": "op", "title__en": "Again", "order": 0})
        self.assertIn("code", taken.errors)

    def test_submission_page_shows_answers_with_the_form_wording(self):
        submission = make_submission(
            self.facility,
            "OPD-1",
            "opd",
            {"clinic": "ent", "information_signage": 4, "would_return": True, "would_return__comment": "Kind staff"},
        )
        response = self.client.get(reverse("admin:patient_feedback_feedbacksubmission_change", args=[submission.pk]))
        self.assertContains(response, "District Hospital, Mysuru")
        self.assertContains(response, "<strong>ENT</strong>", html=True)
        self.assertContains(response, "4 · Very good")
        self.assertContains(response, "Yes — Kind staff")

    def test_submissions_are_read_only(self):
        changelist = reverse("admin:patient_feedback_feedbacksubmission_changelist")
        self.assertEqual(self.client.get(changelist).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:patient_feedback_feedbacksubmission_add")).status_code, 403)

    def test_csv_export_has_a_column_per_answer(self):
        make_submission(
            self.facility,
            "OPD-1",
            "opd",
            {"information_signage": 4, "would_return": True, "would_return__comment": "=cmd()"},
            uhid="12345678901",
        )
        make_submission(self.facility, "IPD-1", "ipd", {"diet": 2})
        response = self.client.post(
            reverse("admin:patient_feedback_feedbacksubmission_changelist"),
            {"action": "export_csv", "_selected_action": FeedbackSubmission.objects.values_list("pk", flat=True)},
        )
        lines = b"".join(response.streaming_content).decode().splitlines()
        self.assertEqual(
            lines[0].split(","),
            [
                "reference_number",
                "submitted_at",
                "facility",
                "form_code",
                "patient_type",
                "language",
                "uhid",
                "information_signage",
                "would_return",
                "would_return__comment",
                "diet",
            ],
        )
        self.assertIn("District Hospital, Mysuru", lines[1])
        self.assertTrue(lines[1].endswith(",4,yes,'=cmd(),"))
        self.assertTrue(lines[2].endswith(",,,,2"))
