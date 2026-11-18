from datetime import timedelta

from care.utils.tests.base import CareAPITestBase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from patient_feedback.admin import FeedbackFormForm, QuestionForm
from patient_feedback.models import FeedbackForm, FeedbackKiosk, FeedbackSubmission
from patient_feedback.tests import PLAIN_STATIC_STORAGES


def make_submission(facility, reference, form_code, patient_type, ratings, method="manual", **extra):
    answers = [
        {"key": key, "type": "rating", "label": key.replace("_", " ").title(), "value": value, "display": str(value)}
        for key, value in ratings.items()
    ]
    answers += extra.pop("answers", [])
    scores = [v for v in ratings.values() if v]
    return FeedbackSubmission.objects.create(
        reference_number=reference,
        facility_external_id=facility.external_id,
        facility_name=facility.name,
        form_code=form_code,
        form_title=form_code.upper(),
        patient_type=patient_type,
        language="en",
        identification_method=method,
        answers=answers,
        ratings=ratings,
        average_rating=sum(scores) / len(scores) if scores else None,
        submitted_at=extra.pop("submitted_at", timezone.now()),
        **extra,
    )


class FeedbackApiTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.facility = self.create_facility(user=self.create_user())
        self.superuser = self.create_super_user()
        yes = {"key": "would_return", "type": "yes_no", "label": "Would return", "value": True, "display": "Yes"}
        no = {**yes, "value": False, "display": "No"}
        make_submission(self.facility, "OPD-1", "opd", "op", {"signage": 5, "wait": 2, "overall": 4}, answers=[yes])
        make_submission(
            self.facility, "OPD-2", "opd", "op", {"signage": 3, "wait": 0, "overall": 3}, "guest", answers=[no]
        )
        make_submission(self.facility, "IPD-1", "ipd", "ip", {"ward_cleanliness": 2, "diet": 1, "overall": 5})
        make_submission(
            self.facility, "IPD-OLD", "ipd", "ip", {"diet": 5}, submitted_at=timezone.now() - timedelta(days=40)
        )
        make_submission(self.create_facility(user=self.create_user()), "ELSEWHERE", "opd", "op", {"overall": 1})

    def url(self, name):
        return reverse(f"patient_feedback_api:{name}", kwargs={"facility_external_id": self.facility.external_id})

    def test_requires_login(self):
        self.assertIn(self.client.get(self.url("facility-summary")).status_code, (401, 403))

    def test_user_without_facility_access_is_denied(self):
        self.client.force_authenticate(self.create_user())
        self.assertEqual(self.client.get(self.url("facility-responses")).status_code, 403)
        self.assertEqual(self.client.get(self.url("facility-summary")).status_code, 403)

    def test_list_filters_by_op_and_ip(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get(self.url("facility-responses"))
        self.assertEqual(response.data["count"], 4)  # other facility excluded
        ip = self.client.get(self.url("facility-responses"), {"patient_type": "ip"})
        self.assertEqual({r["reference_number"] for r in ip.data["results"]}, {"IPD-1", "IPD-OLD"})
        self.assertEqual(ip.data["results"][0]["answers"][0]["key"], "ward_cleanliness")
        guests = self.client.get(self.url("facility-responses"), {"identification_method": "guest"})
        self.assertEqual(guests.data["count"], 1)

    def test_invalid_filters(self):
        self.client.force_authenticate(self.superuser)
        for params in ({"kiosk": "x"}, {"submitted_after": "x"}, {"patient_type": "er"}):
            self.assertEqual(self.client.get(self.url("facility-responses"), params).status_code, 400)

    def test_summary_per_form_with_lowest_attributes(self):
        self.client.force_authenticate(self.superuser)
        since = (timezone.localdate() - timedelta(days=7)).isoformat()
        data = self.client.get(self.url("facility-summary"), {"submitted_after": since}).data
        self.assertEqual(data["total"], 3)
        forms = {f["form"]: f for f in data["forms"]}
        opd = forms["opd"]
        self.assertEqual((opd["total"], opd["patient_type"]), (2, "op"))
        questions = {q["key"]: q for q in opd["questions"]}
        self.assertEqual(questions["wait"]["average"], 2.0)  # "No comments" (0) isn't averaged
        self.assertEqual(questions["wait"]["distribution"]["0"], 1)
        self.assertEqual(opd["lowest"], ["wait", "overall"])
        self.assertEqual(opd["other_questions"][0]["counts"], {"true": 1, "false": 1})
        self.assertEqual(opd["average_rating"], round((5 + 2 + 4 + 3 + 3) / 5, 2))
        self.assertEqual(forms["ipd"]["lowest"], ["diet", "ward_cleanliness"])

    def test_summary_for_ip_only(self):
        self.client.force_authenticate(self.superuser)
        data = self.client.get(self.url("facility-summary"), {"patient_type": "ip"}).data
        self.assertEqual([f["form"] for f in data["forms"]], ["ipd"])
        self.assertEqual(data["total"], 2)

    def test_health(self):
        self.assertEqual(self.client.get(reverse("patient_feedback_api:health")).status_code, 200)


@override_settings(STORAGES=PLAIN_STATIC_STORAGES)
class AdminTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.superuser = self.create_super_user(is_staff=True)
        self.facility = self.create_facility(user=self.superuser)
        self.kiosk = FeedbackKiosk.objects.create(facility=self.facility, name="OPD")
        self.opd = FeedbackForm.objects.get(code="opd", facility__isnull=True)
        self.client.force_login(self.superuser)

    def test_kiosk_change_page_shows_facility_link(self):
        response = self.client.get(reverse("admin:patient_feedback_feedbackkiosk_change", args=[self.kiosk.pk]))
        self.assertContains(response, f"/facility/{self.facility.external_id}/patient_feedback/ipd/?key=")
        self.assertContains(
            response, f"/facility/{self.facility.external_id}/patient_feedback/?key={self.kiosk.access_key}"
        )

    def test_form_page_shows_a_box_per_language(self):
        response = self.client.get(reverse("admin:patient_feedback_feedbackform_change", args=[self.opd.pk]))
        self.assertContains(response, "Title (English)")
        self.assertContains(response, "Title (Kannada)")
        self.assertContains(response, "Question (Kannada)")
        self.assertContains(response, "ಒಪಿಡಿ ಅಭಿಪ್ರಾಯ")

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
        duplicate = QuestionForm(data={**base, "key": "clinic", "type": "text", "options": "[]"})
        self.assertFalse(duplicate.is_valid())
        no_english = FeedbackFormForm(data={"code": "x", "patient_type": "op", "title__en": "", "order": 0})
        self.assertIn("title__en", no_english.errors)
        reserved = FeedbackFormForm(data={"code": "reset", "patient_type": "op", "title__en": "Reset?", "order": 0})
        self.assertIn("code", reserved.errors)

    def test_csv_export_has_a_column_per_question(self):
        make_submission(
            self.facility,
            "OPD-1",
            "opd",
            "op",
            {"signage": 4},
            answers=[
                {"key": "would_return", "type": "yes_no", "value": True, "display": "Yes", "comment": "=cmd()"},
            ],
        )
        make_submission(self.facility, "IPD-1", "ipd", "ip", {"diet": 2})
        response = self.client.post(
            reverse("admin:patient_feedback_feedbacksubmission_changelist"),
            {"action": "export_csv", "_selected_action": FeedbackSubmission.objects.values_list("pk", flat=True)},
        )
        lines = b"".join(response.streaming_content).decode().splitlines()
        header = lines[0].split(",")
        for column in ("reference_number", "patient_type", "signage", "would_return", "would_return__comment", "diet"):
            self.assertIn(column, header)
        self.assertIn("'=cmd()", lines[1])
