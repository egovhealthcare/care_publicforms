import json
from datetime import timedelta

from care.utils.tests.base import CareAPITestBase
from django.forms.models import model_to_dict
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from care_publicforms.admin import feedback_form_form, localized_form
from care_publicforms.models import FeedbackForm, FeedbackSubmission
from care_publicforms.questions import parse_questions
from care_publicforms.services import stored_answer
from care_publicforms.tests import (
    PLAIN_STATIC_STORAGES,
    TEST_LANGUAGE,
    TEST_LANGUAGE_NAME,
    TEST_PLUGIN_CONFIGS,
    plugin_configs,
)


def make_submission(facility, reference, form_code, values, uhid="", **extra):
    """A submission as the kiosk stores it; ``values`` is {key: value}, plus "<key>__comment" for a Why."""
    form = FeedbackForm.objects.get(code=form_code, facility_external_id__isnull=True)
    questions = {question.key: question for question in parse_questions(form.questions)}
    answers = {
        key: stored_answer(questions[key], value, values)
        for key, value in values.items()
        if not key.endswith("__comment")
    }
    submission = FeedbackSubmission.objects.create(
        reference_number=reference,
        facility_external_id=facility.external_id,
        form=form,
        language="en",
        uhid=uhid,
        answers=answers,
    )
    if "submitted_at" in extra:  # auto_now_add ignores a value given on create
        FeedbackSubmission.objects.filter(pk=submission.pk).update(submitted_at=extra["submitted_at"])
    return submission


@override_settings(PLUGIN_CONFIGS=TEST_PLUGIN_CONFIGS)
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
                "would_return": "yes",
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
                "would_return": "no",
            },
        )
        make_submission(self.facility, "IPD-1", "ipd", {"ward_cleanliness": 2, "diet": 1, "overall_satisfaction": 5})
        make_submission(self.facility, "IPD-OLD", "ipd", {"diet": 5}, submitted_at=timezone.now() - timedelta(days=40))
        make_submission(self.create_facility(user=self.create_user()), "ELSEWHERE", "opd", {"overall_satisfaction": 1})

    def url(self, name):
        return reverse(f"care_publicforms_api:{name}", kwargs={"facility_external_id": self.facility.external_id})

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
        self.assertEqual(
            opd.data["results"][0]["answers"]["clinic"],
            {"question": "Clinic visited", "type": "choice", "value": "ent", "answer": "ENT"},
        )

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
        self.assertEqual(ratings["registration_wait"]["question"], "Waiting time at the registration counter")
        self.assertNotIn("staff_behaviour", ratings)  # only questions that were answered
        self.assertEqual(opd["lowest"], ["registration_wait", "overall_satisfaction"])
        self.assertEqual(opd["average_rating"], round((5 + 2 + 4 + 3 + 3) / 5, 2))
        others = {q["key"]: q["counts"] for q in opd["other_questions"]}
        self.assertEqual(others["would_return"], {"yes": 1, "no": 1})
        self.assertEqual(others["clinic"], {"ent": 2})
        self.assertEqual(next(q for q in opd["other_questions"] if q["key"] == "clinic")["labels"], {"ent": "ENT"})
        self.assertEqual(forms["ipd"]["lowest"], ["diet", "ward_cleanliness"])

    def test_summary_still_counts_a_removed_question(self):
        opd = FeedbackForm.objects.get(code="opd", facility_external_id__isnull=True)
        opd.questions = [q for q in opd.questions if q["key"] != "registration_wait"]
        opd.save()
        self.client.force_authenticate(self.superuser)
        data = self.client.get(self.url("facility-summary"), {"form": "opd"}).data
        keys = [q["key"] for q in data["forms"][0]["ratings"]]
        self.assertEqual(keys[-1], "registration_wait")  # after the questions still on the form
        self.assertEqual(data["forms"][0]["ratings"][-1]["average"], 2.0)

    def test_summary_for_ip_only(self):
        self.client.force_authenticate(self.superuser)
        data = self.client.get(self.url("facility-summary"), {"patient_type": "ip"}).data
        self.assertEqual([(f["form"], f["total"]) for f in data["forms"]], [("ipd", 2)])

    def test_health(self):
        self.assertEqual(self.client.get(reverse("care_publicforms_api:health")).status_code, 200)


@override_settings(STORAGES=PLAIN_STATIC_STORAGES, PLUGIN_CONFIGS=TEST_PLUGIN_CONFIGS)
class AdminTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.superuser = self.create_super_user(is_staff=True)
        self.facility = self.create_facility(user=self.superuser, name="District Hospital, Mysuru")
        self.opd = FeedbackForm.objects.get(code="opd", facility_external_id__isnull=True)
        self.client.force_login(self.superuser)

    def test_form_page_shows_a_box_per_language_and_the_page_link(self):
        self.opd.title = {**self.opd.title, TEST_LANGUAGE: "Test title"}
        self.opd.save()
        url = reverse("admin:care_publicforms_feedbackform_change", args=[self.opd.pk])
        response = self.client.get(url)
        self.assertContains(response, "Title (English)")
        self.assertContains(response, f"Title ({TEST_LANGUAGE_NAME})")
        self.assertContains(response, "Test title")
        # The boxes follow the LANGUAGES setting.
        with self.settings(PLUGIN_CONFIGS=plugin_configs(LANGUAGES=["en"])):
            english_only = self.client.get(url)
        self.assertContains(english_only, "Title (English)")
        self.assertNotContains(english_only, f"Title ({TEST_LANGUAGE_NAME})")
        self.assertContains(response, 'name="questions"')
        self.assertContains(response, "&quot;key&quot;: &quot;registration_wait&quot;")  # indented JSON
        self.assertContains(response, escape("/facility/<facility-id>/type/opd/care_publicforms/"))

    def test_facility_is_checked_and_shown_by_id(self):
        base = {"code": "opd", "patient_type": "op", "title__en": "Ours", "order": 0}
        unknown = feedback_form_form()(data={**base, "facility_external_id": "00000000-0000-0000-0000-000000000000"})
        self.assertIn("facility_external_id", unknown.errors)  # no such facility
        known = feedback_form_form()(data={**base, "facility_external_id": str(self.facility.external_id)})
        self.assertTrue(known.is_valid(), known.errors)  # its own "opd", next to the shared one
        own = known.save()
        changelist = self.client.get(reverse("admin:care_publicforms_feedbackform_changelist"))
        self.assertContains(changelist, "District Hospital, Mysuru")
        self.assertContains(changelist, "Every facility")
        page = self.client.get(reverse("admin:care_publicforms_feedbackform_change", args=[own.pk]))
        self.assertContains(page, "District Hospital, Mysuru")

    def test_facility_form_shows_its_full_link(self):
        own = FeedbackForm.objects.create(
            facility_external_id=self.facility.external_id, code="opd", patient_type="op", title={"en": "Ours"}
        )
        response = self.client.get(reverse("admin:care_publicforms_feedbackform_change", args=[own.pk]))
        self.assertContains(
            response, f"http://testserver/facility/{self.facility.external_id}/type/opd/care_publicforms/"
        )

    def test_form_admin_saves_title_and_questions(self):
        questions = [
            {
                "key": "where",
                "type": "choice",
                "text": {"en": "Where did you park?"},
                "options": [{"value": "inside", "en": "Inside the campus"}],
            }
        ]
        form = feedback_form_form()(
            data={
                "code": "parking",
                "patient_type": "op",
                "title__en": "Parking",
                f"title__{TEST_LANGUAGE}": "",
                "order": 3,
                "is_active": True,
                "questions": json.dumps(questions),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual((saved.title, saved.questions), ({"en": "Parking"}, questions))

    def test_text_in_languages_not_offered_is_kept(self):
        self.opd.title = {"en": "OPD feedback", TEST_LANGUAGE: "Test title"}
        self.opd.save()
        with self.settings(PLUGIN_CONFIGS=plugin_configs(LANGUAGES=["en"])):
            form_class = localized_form(FeedbackForm, {"title": ("Title", 1), "description": ("Description", 1)})
        self.assertNotIn(f"title__{TEST_LANGUAGE}", form_class().fields)
        form = form_class(data={**model_to_dict(self.opd), "title__en": "OPD"}, instance=self.opd)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.opd.refresh_from_db()
        self.assertEqual(self.opd.title, {"en": "OPD", TEST_LANGUAGE: "Test title"})

    def test_questions_json_problems_show_on_the_form(self):
        base = {"patient_type": "op", "title__en": "X", "order": 0}
        bad = feedback_form_form()(
            data={**base, "code": "x", "questions": json.dumps([{"key": "a", "type": "choice", "text": {"en": "A"}}])}
        )
        self.assertFalse(bad.is_valid())
        self.assertTrue(any(e.startswith("“a”: a choice needs options") for e in bad.errors["questions"]))
        broken = feedback_form_form()(data={**base, "code": "y", "questions": "[{"})
        self.assertIn("questions", broken.errors)  # not JSON
        no_english = feedback_form_form()(data={**base, "code": "z", "title__en": ""})
        self.assertIn("title__en", no_english.errors)
        taken = feedback_form_form()(data={**base, "code": "opd"})
        self.assertIn("code", taken.errors)

    def test_submission_page_shows_answers_with_the_form_wording(self):
        submission = make_submission(
            self.facility,
            "OPD-1",
            "opd",
            {"clinic": "ent", "information_signage": 4, "would_return": "yes", "would_return__comment": "Kind staff"},
        )
        # Rewording the question later doesn't change what was answered.
        for question in self.opd.questions:
            if question["key"] == "clinic":
                question["text"] = {"en": "Which clinic did you visit?"}
        self.opd.save()
        response = self.client.get(reverse("admin:care_publicforms_feedbacksubmission_change", args=[submission.pk]))
        self.assertContains(response, "Clinic visited")
        self.assertNotContains(response, "Which clinic did you visit?")
        self.assertContains(response, "District Hospital, Mysuru")
        self.assertContains(response, "<strong>ENT</strong>", html=True)
        self.assertContains(response, "4 · Very good")
        self.assertContains(response, "Yes — Kind staff")

    def test_submissions_are_read_only(self):
        changelist = reverse("admin:care_publicforms_feedbacksubmission_changelist")
        self.assertEqual(self.client.get(changelist).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:care_publicforms_feedbacksubmission_add")).status_code, 403)

    def test_csv_export_has_a_column_per_answer(self):
        make_submission(
            self.facility,
            "OPD-1",
            "opd",
            {"information_signage": 4, "would_return": "yes", "would_return__comment": "=cmd()"},
            uhid="12345678901",
        )
        make_submission(self.facility, "IPD-1", "ipd", {"diet": 2})
        response = self.client.post(
            reverse("admin:care_publicforms_feedbacksubmission_changelist"),
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
