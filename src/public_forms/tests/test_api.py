import json
import re
from datetime import timedelta

from care.utils.tests.base import CareAPITestBase
from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.forms.models import model_to_dict
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from public_forms.admin import feedback_form_form, localized_form
from public_forms.models import FeedbackForm, FeedbackSubmission
from public_forms.questions import parse_questions
from public_forms.services import stored_answer
from public_forms.tests import (
    PLAIN_STATIC_STORAGES,
    TEST_LANGUAGE,
    TEST_LANGUAGE_NAME,
    TEST_PLUGIN_CONFIGS,
    default_forms,
    plugin_configs,
    questions_of,
)


def make_submission(facility, reference, form_code, values, uhid="", **extra):
    """A submission as the kiosk stores it; ``values`` is {key: value}, plus "<key>__comment" for a Why."""
    form = default_forms(facility)[form_code]
    questions = {question.key: question for question in parse_questions(form.pages)}
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
        return reverse(f"public_forms_api:{name}", kwargs={"facility_external_id": self.facility.external_id})

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
        opd = FeedbackForm.objects.get(code="opd", facility_external_id=self.facility.external_id)
        for page in opd.pages:
            page["questions"] = [q for q in page["questions"] if q["key"] != "registration_wait"]
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
        self.assertEqual(self.client.get(reverse("public_forms_api:health")).status_code, 200)


@override_settings(STORAGES=PLAIN_STATIC_STORAGES, PLUGIN_CONFIGS=TEST_PLUGIN_CONFIGS)
class AdminTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.superuser = self.create_super_user(is_staff=True)
        self.facility = self.create_facility(user=self.superuser, name="District Hospital, Mysuru")
        self.opd = default_forms(self.facility)["opd"]
        self.client.force_login(self.superuser)

    def test_form_page_shows_a_box_per_language_and_the_page_link(self):
        self.opd.title = {**self.opd.title, TEST_LANGUAGE: "Test title"}
        self.opd.save()
        url = reverse("public_forms_admin:public_forms_feedbackform_change", args=[self.opd.pk])
        response = self.client.get(url)
        self.assertContains(response, "Title (English)")
        self.assertContains(response, f"Title ({TEST_LANGUAGE_NAME})")
        self.assertContains(response, "Test title")
        # The boxes follow the LANGUAGES setting.
        with self.settings(PLUGIN_CONFIGS=plugin_configs(LANGUAGES=["en"])):
            english_only = self.client.get(url)
        self.assertContains(english_only, "Title (English)")
        self.assertNotContains(english_only, f"Title ({TEST_LANGUAGE_NAME})")
        self.assertContains(response, 'name="pages"')
        self.assertContains(response, "&quot;key&quot;: &quot;registration_wait&quot;")  # indented JSON
        self.assertContains(
            response, f"http://testserver/facility/{self.facility.external_id}/public_forms/type/opd/form/"
        )

    def test_facility_is_required_checked_and_shown_by_name(self):
        base = {"code": "eye_opd", "patient_type": "op", "title__en": "Eye OPD", "order": 0}
        missing = feedback_form_form()(data=base)
        self.assertIn("facility_external_id", missing.errors)  # every form belongs to a facility
        unknown = feedback_form_form()(data={**base, "facility_external_id": "00000000-0000-0000-0000-000000000000"})
        self.assertIn("facility_external_id", unknown.errors)  # no such facility
        taken = feedback_form_form()(
            data={**base, "code": "opd", "facility_external_id": str(self.facility.external_id)}
        )
        self.assertIn("code", taken.errors)  # the facility has an "opd" form already
        known = feedback_form_form()(data={**base, "facility_external_id": str(self.facility.external_id)})
        self.assertTrue(known.is_valid(), known.errors)
        own = known.save()
        changelist = self.client.get(reverse("public_forms_admin:public_forms_feedbackform_changelist"))
        self.assertContains(changelist, "District Hospital, Mysuru", count=3)  # opd, ipd and eye_opd
        page = self.client.get(reverse("public_forms_admin:public_forms_feedbackform_change", args=[own.pk]))
        self.assertContains(page, "District Hospital, Mysuru")

    def test_form_admin_saves_title_and_pages(self):
        pages = [
            {
                "title": {"en": "Parking"},
                "primary_button": {"en": "Rate us"},
                "questions": [
                    {
                        "key": "where",
                        "type": "choice",
                        "text": {"en": "Where did you park?"},
                        "options": [{"value": "inside", "en": "Inside the campus"}],
                    }
                ],
            },
            {"questions": [{"key": "space", "type": "rating", "text": {"en": "Was there space?"}}]},
        ]
        form = feedback_form_form()(
            data={
                "facility_external_id": str(self.facility.external_id),
                "code": "parking",
                "patient_type": "op",
                "title__en": "Parking",
                f"title__{TEST_LANGUAGE}": "",
                "order": 3,
                "is_active": True,
                "pages": json.dumps(pages),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.title, {"en": "Parking"})
        self.assertEqual(saved.pages, pages)
        # The old format, a list of questions, says what changed.
        old = feedback_form_form()(
            data={**form.data, "code": "parking_old", "pages": json.dumps(pages[0]["questions"])}
        )
        self.assertFalse(old.is_valid())
        self.assertTrue(old.errors["pages"][0].startswith("Page 1: looks like a question."), old.errors)

    def test_title_and_description_follow_the_text_rules(self):
        base = {"code": "x", "patient_type": "op", "order": 0}
        form = feedback_form_form()(
            data={**base, "title__en": "<b>Ours</b>", f"description__{TEST_LANGUAGE}": "Uses `ticks`"}
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["title__en"], ["Don't use these characters: < >"])
        self.assertEqual(form.errors[f"description__{TEST_LANGUAGE}"], ["Don't use these characters: `"])
        too_long = feedback_form_form()(data={**base, "title__en": "x" * 101})
        self.assertIn("at most 100 characters", too_long.errors["title__en"][0])
        self.assertIn('maxlength="100"', str(too_long["title__en"]))

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

    def test_pages_json_problems_show_on_the_form(self):
        base = {
            "patient_type": "op",
            "title__en": "X",
            "order": 0,
            "facility_external_id": str(self.facility.external_id),
        }
        page = {"questions": [{"key": "a", "type": "choice", "text": {"en": "A"}}]}
        bad = feedback_form_form()(data={**base, "code": "x", "pages": json.dumps([page])})
        self.assertFalse(bad.is_valid())
        self.assertTrue(any(e.startswith("“a”: a choice needs options") for e in bad.errors["pages"]))
        broken = feedback_form_form()(data={**base, "code": "y", "pages": "[{"})
        self.assertIn("pages", broken.errors)  # not JSON
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
        for question in questions_of(self.opd):
            if question["key"] == "clinic":
                question["text"] = {"en": "Which clinic did you visit?"}
        self.opd.save()
        response = self.client.get(
            reverse("public_forms_admin:public_forms_feedbacksubmission_change", args=[submission.pk])
        )
        self.assertContains(response, "Clinic visited")
        self.assertNotContains(response, "Which clinic did you visit?")
        self.assertContains(response, "District Hospital, Mysuru")
        self.assertContains(response, "<strong>ENT</strong>", html=True)
        self.assertContains(response, "4 · Very good")
        self.assertContains(response, "Yes (Kind staff)")

    def test_submission_page_keeps_line_breaks_and_escapes(self):
        submission = make_submission(
            self.facility,
            "OPD-1",
            "opd",
            {"clinic": "ent", "improvement": "Shorter queues.\nMore seats & <b>chairs</b>.\n\nThanks"},
        )
        response = self.client.get(
            reverse("public_forms_admin:public_forms_feedbacksubmission_change", args=[submission.pk])
        )
        self.assertContains(response, "Shorter queues.<br>More seats &amp; &lt;b&gt;chairs&lt;/b&gt;.<br><br>Thanks")

    def test_submissions_are_read_only(self):
        changelist = reverse("public_forms_admin:public_forms_feedbacksubmission_changelist")
        self.assertEqual(self.client.get(changelist).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("public_forms_admin:public_forms_feedbacksubmission_add")).status_code, 403
        )

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
            reverse("public_forms_admin:public_forms_feedbacksubmission_changelist"),
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


@override_settings(STORAGES=PLAIN_STATIC_STORAGES, PLUGIN_CONFIGS=TEST_PLUGIN_CONFIGS)
class AdminSiteTests(CareAPITestBase):
    """The admin is its own site at /public_forms/admin/, apart from Django's /admin/."""

    password = "test-only-Pw-4821"

    def sign_in(self, user, password=None):
        # As the sign-in page posts it, with its hidden "next" (the admin's index).
        data = {"username": user.username, "password": password or self.password}
        return self.client.post(
            reverse("public_forms_admin:login"), {**data, "next": reverse("public_forms_admin:index")}
        )

    def test_screens_are_off_djangos_admin(self):
        self.assertEqual(reverse("public_forms_admin:index"), "/public_forms/admin/")
        self.assertNotIn(FeedbackForm, admin.site._registry)
        self.assertNotIn(FeedbackSubmission, admin.site._registry)
        self.client.force_login(self.create_super_user(is_staff=True))
        old = f"{reverse('admin:index')}public_forms/feedbackform/"
        self.assertEqual(self.client.get(old).status_code, 404)
        forms = self.client.get(reverse("public_forms_admin:public_forms_feedbackform_changelist"))
        self.assertContains(forms, "Public Forms")

    def test_no_links_into_djangos_admin(self):
        superuser = self.create_super_user(is_staff=True)
        # An action logged in Django's admin, which "Recent actions" would list and link to.
        LogEntry.objects.create(
            user=superuser,
            content_type=ContentType.objects.get_for_model(superuser),
            object_id=str(superuser.pk),
            object_repr="a user",
            action_flag=CHANGE,
            change_message="[]",
        )
        self.client.force_login(superuser)
        index = self.client.get(reverse("public_forms_admin:index"))
        self.assertContains(index, "Feedback submissions")
        self.assertNotContains(index, "recent-actions-module")
        hrefs = re.findall(r'href="([^"]*)"', index.content.decode())
        self.assertTrue(hrefs)
        self.assertEqual([href for href in hrefs if href.startswith(reverse("admin:index"))], [])

    def test_signing_in_is_required(self):
        index = reverse("public_forms_admin:index")
        self.assertRedirects(
            self.client.get(index), f"{reverse('public_forms_admin:login')}?next={index}", fetch_redirect_response=False
        )

    def test_this_apps_permission_opens_it_without_staff_access(self):
        user = self.create_user_with_password(self.password, is_staff=False, is_superuser=False)
        response = self.sign_in(user)
        self.assertContains(response, "an account that can manage feedback forms")
        self.assertNotIn("_auth_user_id", self.client.session)

        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="public_forms", codename="view_feedbacksubmission")
        )
        self.assertRedirects(self.sign_in(user), reverse("public_forms_admin:index"), fetch_redirect_response=False)
        submissions = reverse("public_forms_admin:public_forms_feedbacksubmission_changelist")
        self.assertEqual(self.client.get(submissions).status_code, 200)
        # Only what the permissions allow: viewing submissions, not the forms.
        forms = reverse("public_forms_admin:public_forms_feedbackform_changelist")
        self.assertEqual(self.client.get(forms).status_code, 403)
        # The rest of Django's admin stays closed.
        self.assertRedirects(
            self.client.get(reverse("admin:index")),
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
            fetch_redirect_response=False,
        )

    @override_settings(DISABLE_RATELIMIT=False, PLUGIN_CONFIGS=plugin_configs(ADMIN_LOGIN_RATE_LIMIT="2/m"))
    def test_sign_in_attempts_are_rate_limited(self):
        cache.clear()  # the counts live in the cache
        user = self.create_user_with_password(self.password, is_superuser=True)
        for _attempt in range(2):
            self.assertContains(self.sign_in(user, "wrong"), "an account that can manage feedback forms")
        response = self.sign_in(user)  # the right password, but too soon
        self.assertContains(response, "Too many sign-in attempts")
        self.assertNotIn("_auth_user_id", self.client.session)
