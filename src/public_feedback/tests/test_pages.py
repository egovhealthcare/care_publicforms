import uuid
from datetime import timedelta
from unittest import mock

from care.utils.tests.base import CareAPITestBase
from django.db.models import ProtectedError
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.http import urlencode

from public_feedback.checks import check_languages
from public_feedback.models import Audience, FeedbackForm, FeedbackSubmission, QuestionType
from public_feedback.questionnaire import FormSpec, applies
from public_feedback.questions import question_errors
from public_feedback.tests import PLAIN_STATIC_STORAGES, PLUGIN_DEFAULTS

UHID = "12345678901"


@override_settings(STORAGES=PLAIN_STATIC_STORAGES, PLUGIN_CONFIGS=PLUGIN_DEFAULTS)
class PageTestBase(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.facility = self.create_facility(user=self.create_user(), name="District Hospital, Mysuru")
        # Seeded by the 0002 data migration
        self.opd = FeedbackForm.objects.get(code="opd", facility_external_id__isnull=True)
        self.ipd = FeedbackForm.objects.get(code="ipd", facility_external_id__isnull=True)

    def url(self, name="start", form=None, facility=None, **query):
        kwargs = {"facility_id": (facility or self.facility).external_id}
        if form:
            kwargs["form"] = form
        url = reverse(f"public_feedback:{name}", kwargs=kwargs)
        return f"{url}?{urlencode(query)}" if query else url

    def ratings(self, form, value=5, identified=True):
        return {q.key: value for q in FormSpec(form).ratings if applies(q, identified)}

    def details(self, form, identified=True):
        values = {
            "clinic": "ent",
            "ward": "surgery",
            "date_of_admission": (timezone.localdate() - timedelta(days=3)).isoformat(),
            "age_group": "31_45",
            "sex": "female",
        }
        return {q.key: values[q.key] for q in FormSpec(form).details if q.required and applies(q, identified)}

    def add_question(self, form, key, **fields):
        form.questions = [*form.questions, {"key": key, "text": {"en": key.replace("_", " ").capitalize()}, **fields}]
        form.save()

    @staticmethod
    def values(answers):
        """The stored answers' values, {key: value}."""
        return {key: entry["value"] for key, entry in answers.items()}

    def answers(self, form, value=5, identified=True):
        """Every required answer, as a complete submission sends them."""
        return {**self.details(form, identified), **self.ratings(form, value, identified)}

    def submit(self, form="opd", **data):
        return self.client.post(self.url("form", form), data)


class PublicPageTests(PageTestBase):
    def test_pages_live_under_the_facility(self):
        base = f"/facility/{self.facility.external_id}"
        self.assertEqual(self.url(), f"{base}/public_feedback/")
        self.assertEqual(self.url("form", "ipd"), f"{base}/type/ipd/public_feedback/")
        self.assertEqual(self.url("done", "ipd"), f"{base}/type/ipd/public_feedback/done/")
        # Typed without the trailing slash
        self.assertRedirects(
            self.client.get(f"{base}/type/ipd/public_feedback"),
            f"{base}/type/ipd/public_feedback/",
            status_code=301,
            fetch_redirect_response=False,
        )

    def test_chooser_is_public_and_sets_no_cookies(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(dict(response.cookies), {})
        self.assertContains(response, self.url("form", "opd", **{"from": "start"}))
        self.assertContains(response, self.url("form", "ipd", **{"from": "start"}))

    def test_a_single_form_opens_directly(self):
        FeedbackForm.objects.filter(code="ipd").update(is_active=False)
        self.assertRedirects(self.client.get(self.url()), self.url("form", "opd"), fetch_redirect_response=False)

    def test_unknown_facility_and_no_forms(self):
        response = self.client.get(self.url(facility=mock.Mock(external_id=uuid.uuid4())))
        self.assertContains(response, "This facility wasn't found.", status_code=404)
        FeedbackForm.objects.update(is_active=False)
        self.assertContains(self.client.get(self.url()), "No feedback forms are set up", status_code=404)

    def test_unknown_form_goes_to_the_chooser(self):
        self.assertRedirects(self.client.get(self.url("form", "nope")), self.url(), fetch_redirect_response=False)

    def test_form_page_holds_every_step_and_language(self):
        response = self.client.get(self.url("form", "opd"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(dict(response.cookies), {})
        for step in ("identify", "scan", "uhid", "details", "questions", "comments", "review"):
            self.assertContains(response, f'data-step="{step}"')
        self.assertContains(response, "data-card", count=len(FormSpec(self.opd).ratings))
        self.assertContains(response, 'class="l10n l10n--kn"')
        self.assertContains(response, 'name="information_signage"')
        self.assertContains(response, 'data-audience="guest"')
        self.assertContains(response, f'data-home-url="{self.url("form", "opd")}"')
        self.assertNotContains(response, "csrfmiddlewaretoken")

    def test_home_and_reset_links(self):
        # kiosk.js shows them from the first rating question on, in every flow.
        chosen = self.client.get(self.url("form", "opd", **{"from": "start"}))
        self.assertContains(chosen, '<nav class="hdr-nav" id="hdrNav" hidden>')
        # Picked on the chooser: Home → chooser, Reset → this form.
        self.assertContains(chosen, f'class="navbtn navbtn--home" href="{self.url()}"')
        reset = self.url("form", "opd", **{"from": "start"})
        self.assertContains(chosen, f'class="navbtn navbtn--reset" href="{reset}"')
        # Pinned to the form: both start the form over.
        pinned = self.client.get(self.url("form", "opd"))
        self.assertContains(pinned, '<nav class="hdr-nav" id="hdrNav" hidden>')
        self.assertContains(pinned, f'class="navbtn navbtn--home" href="{self.url("form", "opd")}"')

    def test_screen_options_in_the_url(self):
        response = self.client.get(self.url(lang="kn", scan="off", keypad="0"))
        self.assertContains(response, 'data-lang="kn"')
        link = self.url("form", "opd", lang="kn", scan="off", keypad="0", **{"from": "start"})
        self.assertContains(response, escape(link))
        page = self.client.get(self.url("form", "opd", scan="off", keypad="0"))
        self.assertNotContains(page, 'data-step="scan"')
        self.assertNotContains(page, 'id="keypad"')

    def test_posting_needs_no_csrf_token_or_session(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(self.url("form", "opd"), {"uhid": UHID, **self.answers(self.opd)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(dict(response.cookies), {})
        self.assertEqual(FeedbackSubmission.objects.count(), 1)


class SubmitTests(PageTestBase):
    def test_identified_submission_keeps_only_what_is_needed(self):
        response = self.submit(
            uhid="123-4567-8901",
            language="kn",
            clinic="ent",
            age_group="18_30",  # guests only: ignored once a UHID is given
            would_return="yes",
            would_return__comment="  Friendly staff ",
            improvement="",
            **self.ratings(self.opd, 4),
        )
        submission = FeedbackSubmission.objects.get()
        self.assertRedirects(
            response,
            self.url("done", "opd", ref=submission.reference_number, language="kn"),
            fetch_redirect_response=False,
        )
        self.assertEqual(submission.uhid, UHID)
        self.assertEqual(
            (submission.facility_external_id, submission.form, submission.language),
            (self.facility.external_id, self.opd, "kn"),
        )
        self.assertEqual(
            self.values(submission.answers),
            {**self.ratings(self.opd, 4), "clinic": "ent", "would_return": True},
        )
        # Each answer keeps its question as asked, in English, with the label picked.
        self.assertEqual(
            submission.answers["registration_wait"],
            {
                "question": "Waiting time at the registration counter",
                "type": "rating",
                "value": 4,
                "answer": "Within 5 mins",
            },
        )
        self.assertEqual(
            submission.answers["clinic"],
            {"question": "Clinic visited", "type": "choice", "value": "ent", "answer": "ENT"},
        )
        self.assertEqual(
            submission.answers["would_return"],
            {
                "question": "Would you come back to this hospital for treatment?",
                "type": "boolean",
                "value": True,
                "comment": "Friendly staff",
            },
        )

    def test_the_only_relation_is_submission_to_form(self):
        # No links into Care (facilities are kept by id); a submission belongs to its form.
        relations = {
            (model.__name__, f.name, f.related_model.__name__)
            for model in (FeedbackForm, FeedbackSubmission)
            for f in model._meta.get_fields()
            if f.is_relation
        }
        self.assertEqual(
            relations,
            {("FeedbackSubmission", "form", "FeedbackForm"), ("FeedbackForm", "submissions", "FeedbackSubmission")},
        )
        fields = FeedbackSubmission._meta.get_fields()
        self.assertEqual(
            {f.name for f in fields},
            {
                "id",
                "external_id",
                "reference_number",
                "facility_external_id",
                "form",
                "language",
                "uhid",
                "answers",
                "submitted_at",
            },
        )

    def test_guest_answers_guest_questions(self):
        self.submit(**self.answers(self.opd, 3, identified=False))
        submission = FeedbackSubmission.objects.get()
        self.assertEqual(submission.uhid, "")
        self.assertEqual(submission.answers["age_group"]["value"], "31_45")
        self.assertEqual(submission.answers["sex"]["answer"], "Female")
        self.assertEqual(submission.language, "en")

    def test_missing_ratings_show_the_page_again(self):
        ratings = self.ratings(self.opd)
        first_missing = list(ratings)[2]
        del ratings[first_missing]
        response = self.submit(uhid=UHID, clinic="ent", **ratings)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FeedbackSubmission.objects.exists())
        self.assertEqual(response.context["errors"], {first_missing: "required"})
        self.assertEqual((response.context["current_step"], response.context["current_card"]), ("questions", 2))
        self.assertEqual(response.context["banner"], "error_summary")
        # What was entered is kept.
        self.assertContains(response, f'value="{UHID}"')
        self.assertContains(response, 'value="ent" checked')

    def test_bad_uhid_opens_the_uhid_step(self):
        response = self.submit(uhid="123", **self.ratings(self.opd))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_step"], "uhid")
        self.assertFalse(FeedbackSubmission.objects.exists())

    def test_details_need_answers(self):
        guest = self.submit(**self.ratings(self.opd, identified=False))
        self.assertEqual(guest.context["errors"], dict.fromkeys(("clinic", "age_group", "sex"), "required"))
        self.assertEqual(guest.context["current_step"], "details")
        identified = self.submit(uhid=UHID, **self.ratings(self.opd))  # age and sex are asked of guests only
        self.assertEqual(identified.context["errors"], {"clinic": "required"})
        self.assertContains(identified, 'data-question-key="clinic" data-audience="all" data-required="1"')
        self.assertFalse(FeedbackSubmission.objects.exists())

    def test_invalid_values(self):
        future = (timezone.localdate() + timedelta(days=2)).isoformat()
        response = self.submit("ipd", uhid=UHID, ward="nope", date_of_admission=future, **self.ratings(self.ipd))
        self.assertEqual(response.context["errors"], {"ward": "required", "date_of_admission": "invalid"})
        # A future date gets its own message, not "needs an answer".
        self.assertContains(response, 'data-error-date role="alert">')
        response = self.submit("ipd", uhid=UHID, **{**self.answers(self.ipd), "diet": "9"})
        self.assertEqual(response.context["errors"], {"diet": "required"})
        # An invalid optional answer is dropped.
        self.submit("ipd", uhid=UHID, would_return="maybe", **self.answers(self.ipd))
        self.assertEqual(self.values(FeedbackSubmission.objects.get().answers), self.answers(self.ipd))

    def test_why_without_yes_or_no_is_dropped(self):
        self.submit(uhid=UHID, would_return__comment="Kind staff", **self.answers(self.opd))
        self.assertNotIn("would_return", FeedbackSubmission.objects.get().answers)

    def test_reference_number_uses_the_form_code(self):
        self.submit(uhid=UHID, **self.answers(self.opd))
        reference = FeedbackSubmission.objects.get().reference_number
        self.assertRegex(reference, rf"^OPD-{timezone.localdate():%Y%m%d}-\d{{4}}$")

    @override_settings(PLUGIN_CONFIGS={"public_feedback": {"REFERENCE_PREFIX": "PF"}})
    def test_reference_prefix_setting(self):
        self.submit("ipd", **self.answers(self.ipd, identified=False))
        self.assertTrue(FeedbackSubmission.objects.get().reference_number.startswith("PF-"))

    def test_long_form_code_still_fits_the_reference(self):
        long_form = FeedbackForm.objects.create(
            code="general_medicine_ward_feedback",
            patient_type="ip",
            title={"en": "Ward"},
            questions=[{"key": "care", "type": "rating", "text": {"en": "Care"}}],
        )
        self.assertEqual(self.submit(long_form.code, care="4").status_code, 302)
        reference = FeedbackSubmission.objects.get().reference_number
        self.assertTrue(reference.startswith("GENERAL_MEDI-"))
        self.assertLessEqual(len(reference), FeedbackSubmission._meta.get_field("reference_number").max_length)

    def test_reference_collisions_are_retried(self):
        with mock.patch("public_feedback.services.secrets.randbelow", side_effect=[1111, 1111, 2222]):
            self.submit(uhid=UHID, **self.answers(self.opd))
            self.submit(uhid=UHID, **self.answers(self.opd))
        numbers = sorted(FeedbackSubmission.objects.values_list("reference_number", flat=True))
        self.assertEqual([n[-4:] for n in numbers], ["2111", "3222"])

    def test_rate_limited(self):
        with (
            mock.patch("public_feedback.views.is_ratelimited", return_value=True),
            self.settings(DISABLE_RATELIMIT=False),
        ):
            response = self.submit(uhid=UHID, **self.answers(self.opd))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.context["banner"], "too_many")
        # Answers are kept and the page opens on the review, ready to submit again.
        self.assertEqual(response.context["current_step"], "review")
        self.assertFalse(FeedbackSubmission.objects.exists())

    @override_settings(DISABLE_RATELIMIT=False, PLUGIN_CONFIGS={"public_feedback": {"SUBMIT_RATE_LIMIT": ""}})
    def test_empty_rate_limit_turns_it_off(self):
        with mock.patch("public_feedback.views.is_ratelimited", return_value=True):
            self.assertEqual(self.submit(uhid=UHID, **self.answers(self.opd)).status_code, 302)

    def test_idle_timer_starts_at_once_on_a_patients_page(self):
        armed, unarmed = 'data-idle-armed="1"', 'data-idle-armed="0"'
        self.assertContains(self.client.get(self.url("form", "opd")), unarmed)  # fresh screen
        self.assertContains(self.client.get(self.url()), unarmed)
        self.assertContains(self.client.get(self.url(language="kn")), armed)  # their language
        self.assertContains(self.client.get(self.url("form", "opd", **{"from": "start"})), armed)  # their form
        self.assertContains(self.submit(uhid=UHID), armed)  # their answers, after a failed submit


class DoneTests(PageTestBase):
    def done_page(self, **data):
        response = self.submit(uhid=UHID, **self.answers(self.opd), **data)
        return self.client.get(response["Location"]), FeedbackSubmission.objects.latest("submitted_at")

    def test_shows_the_reference_and_returns_to_the_form(self):
        response, submission = self.done_page()
        self.assertContains(response, submission.reference_number)
        self.assertContains(response, f'content="20;url={self.url("form", "opd")}"')

    def test_returns_to_the_chooser_when_started_there(self):
        response, _ = self.done_page(**{"from": "start"})
        self.assertContains(response, f'content="20;url={self.url()}"')

    def test_unknown_reference_goes_back_to_the_start(self):
        self.done_page()
        for form, ref in (("opd", "OPD-0"), ("ipd", FeedbackSubmission.objects.get().reference_number)):
            self.assertRedirects(
                self.client.get(self.url("done", form, ref=ref)),
                self.url("form", form),
                fetch_redirect_response=False,
            )


class ConfigurationTests(PageTestBase):
    def test_switching_off_a_facility_form_hides_the_code(self):
        FeedbackForm.objects.create(
            facility_external_id=self.facility.external_id,
            code="opd",
            patient_type="op",
            title={"en": "Our OPD"},
            is_active=False,
        )
        self.assertRedirects(self.client.get(self.url()), self.url("form", "ipd"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(self.url("form", "opd")), self.url(), fetch_redirect_response=False)

    def test_facility_form_replaces_the_shared_one(self):
        own = FeedbackForm.objects.create(
            facility_external_id=self.facility.external_id,
            code="opd",
            patient_type="op",
            title={"en": "Our OPD"},
            order=1,
        )
        self.add_question(own, "cleanliness", type=QuestionType.RATING)
        page = self.client.get(self.url("form", "opd"))
        self.assertContains(page, "data-card", count=1)
        self.assertContains(page, "Our OPD")
        self.submit(cleanliness="5")
        self.assertEqual(
            FeedbackSubmission.objects.get().answers,
            {"cleanliness": {"question": "Cleanliness", "type": "rating", "value": 5, "answer": "Excellent"}},
        )
        # Other facilities keep the shared form.
        elsewhere = self.create_facility(user=self.create_user())
        self.assertContains(
            self.client.get(self.url("form", "opd", facility=elsewhere)),
            "data-card",
            count=len(FormSpec(self.opd).ratings),
        )

    def test_inactive_and_new_questions(self):
        dropped = next(q for q in self.opd.questions if q["type"] == QuestionType.RATING)
        dropped["active"] = False
        self.opd.save()
        dropped = mock.Mock(key=dropped["key"])
        self.add_question(self.opd, "parking", type=QuestionType.TEXT, required=True)
        page = self.client.get(self.url("form", "opd"))
        self.assertNotContains(page, f'name="{dropped.key}"')
        self.assertContains(page, 'name="parking"')
        response = self.submit(uhid=UHID, **self.answers(self.opd))
        self.assertEqual(response.context["errors"], {"parking": "required"})
        self.assertEqual(response.context["current_step"], "comments")
        self.submit(uhid=UHID, parking="Inside", **self.answers(self.opd))
        self.assertEqual(FeedbackSubmission.objects.get().answers["parking"]["value"], "Inside")

    def test_questions_for_identified_patients_only(self):
        self.add_question(self.opd, "doctor_name_known", type=QuestionType.RATING, audience=Audience.IDENTIFIED)
        guest = self.submit(**self.answers(self.opd, identified=False))
        self.assertEqual(guest.status_code, 302)
        identified = self.submit(uhid=UHID, **self.answers(self.opd, identified=False))
        self.assertEqual(identified.context["errors"], {"doctor_name_known": "required"})


class LanguageTests(PageTestBase):
    def test_patient_language_lasts_until_the_thank_you_page(self):
        start = {"from": "start"}
        # Chosen on the chooser: its form links carry it.
        chooser = self.client.get(self.url(language="kn"))
        self.assertContains(chooser, 'data-lang="kn"')
        self.assertContains(chooser, escape(self.url("form", "opd", **start, language="kn")))
        self.assertContains(chooser, f'data-home-url="{self.url()}"')
        # The form opens in it, and Back / Home / Reset keep it.
        page = self.client.get(self.url("form", "opd", **start, language="kn"))
        self.assertContains(page, 'data-lang="kn"')
        self.assertContains(page, 'name="language" value="kn"')
        self.assertContains(page, f'href="{self.url(language="kn")}" data-carry-lang', count=2)  # Back, Home
        self.assertContains(page, escape(self.url("form", "opd", **start, language="kn")) + '" data-action="reset"')
        # Without JavaScript the toggle posts the form, so the answers stay; on the chooser it is a link.
        self.assertContains(page, 'form="feedback" name="nav" value="lang:en"')
        self.assertContains(chooser, 'href="?language=en"')
        # The idle reset is for the next patient: the screen's own language.
        self.assertContains(page, f'data-home-url="{self.url()}"')
        # Submitted in it, the thank-you page stays in it; its return does not.
        response = self.client.post(
            page.request["PATH_INFO"] + "?" + page.request["QUERY_STRING"],
            {"uhid": UHID, "language": "kn", **start, **self.answers(self.opd)},
        )
        self.assertEqual(FeedbackSubmission.objects.get().language, "kn")
        done = self.client.get(response["Location"])
        self.assertContains(done, 'data-lang="kn"')
        self.assertContains(done, f'content="20;url={self.url()}"')

    def test_patient_language_and_screen_language(self):
        # A Kannada screen (?lang=kn) where the patient switched to English.
        chooser = self.client.get(self.url(lang="kn", language="en"))
        self.assertContains(chooser, 'data-lang="en"')
        self.assertContains(chooser, escape(self.url("form", "opd", lang="kn", **{"from": "start"}, language="en")))
        self.assertContains(chooser, f'data-home-url="{self.url(lang="kn")}"')

    @override_settings(PLUGIN_CONFIGS={"public_feedback": {"LANGUAGES": ["en"]}})
    def test_one_language_hides_the_toggle(self):
        page = self.client.get(self.url("form", "opd"))
        self.assertNotContains(page, 'class="langtog"')
        self.assertNotContains(page, "l10n--kn")
        self.assertNotContains(page, "Noto")
        self.assertContains(page, 'class="l10n l10n--en"')
        self.assertContains(self.client.get(self.url("form", "opd", lang="kn")), 'data-lang="en"')

    @override_settings(PLUGIN_CONFIGS={"public_feedback": {"LANGUAGES": ["kn", "en", "xx"], "DEFAULT_LANGUAGE": "kn"}})
    def test_order_default_and_unknown_codes(self):
        page = self.client.get(self.url("form", "opd"))
        content = page.content.decode()
        self.assertContains(page, 'data-lang="kn"')
        self.assertLess(content.index('data-set-lang="kn"'), content.index('data-set-lang="en"'))
        self.assertNotContains(page, "xx")
        self.assertEqual([w.id for w in check_languages(None)], ["public_feedback.W001"])

    @override_settings(PLUGIN_CONFIGS={"public_feedback": {"LANGUAGES": ["en"], "DEFAULT_LANGUAGE": "kn"}})
    def test_default_language_must_be_offered(self):
        self.assertContains(self.client.get(self.url("form", "opd")), 'data-lang="en"')
        self.assertEqual([w.id for w in check_languages(None)], ["public_feedback.W002"])

    def test_defaults_raise_no_warnings(self):
        self.assertEqual(check_languages(None), [])


class StepByStepWithoutJavaScriptTests(PageTestBase):
    """Without JavaScript every step button posts the page; the server shows the step it leads to."""

    def press(self, nav, form="opd", **data):
        return self.client.post(self.url("form", form), {"nav": nav, **data})

    def place(self, response):
        return response.context["current_step"], response.context["current_card"]

    def test_the_first_page_offers_uhid_and_guest(self):
        page = self.client.get(self.url("form", "opd"))
        self.assertEqual(self.place(page), ("identify", 0))
        self.assertContains(page, 'class="step screen screen--start is-active"')
        self.assertContains(page, 'name="nav" value="go:uhid"')
        self.assertContains(page, 'name="nav" value="guest"')
        self.assertContains(page, 'class="opt opt--scan js-only"')  # the camera needs JavaScript
        # Enter presses the form's first submit button: it must be "default", not a language button.
        content = page.content.decode()
        self.assertLess(content.index('name="nav" value="default"'), content.index('name="nav" value="lang:'))

    def test_an_identified_patient_walks_every_step(self):
        keys = list(self.ratings(self.opd))
        self.assertEqual(self.place(self.press("go:uhid", step="identify")), ("uhid", 0))
        wrong = self.press("uhid", step="uhid", uhid="12345")
        self.assertEqual((self.place(wrong), wrong.context["errors"]), (("uhid", 0), {"uhid": "length"}))
        # Enter in the UHID field presses the hidden first button: "default" continues.
        details = self.press("default", step="uhid", uhid=UHID)
        self.assertEqual(self.place(details), ("details", 0))
        self.assertContains(details, 'id="idStripValue">123 4567 8901<')
        self.assertContains(details, 'data-question-key="age_group" data-audience="guest" data-required="1" hidden')

        missing = self.press("next", step="details", uhid=UHID)
        self.assertEqual((self.place(missing), missing.context["errors"]), (("details", 0), {"clinic": "required"}))
        answers = {"uhid": UHID, "clinic": "ent"}
        first = self.press("next", step="details", **answers)
        self.assertEqual(self.place(first), ("questions", 0))
        self.assertContains(first, '<nav class="hdr-nav" id="hdrNav">')
        unanswered = self.press("next", step="questions", card=0, **answers)
        self.assertEqual(unanswered.context["errors"], {keys[0]: "required"})

        for card, key in enumerate(keys):
            answers[key] = "4"
            response = self.press("next", step="questions", card=card, **answers)
            expected = ("questions", card + 1) if card + 1 < len(keys) else ("comments", 0)
            self.assertEqual(self.place(response), expected)
        review = self.press("next", step="comments", would_return="yes", **answers)
        self.assertEqual(self.place(review), ("review", 0))
        self.assertEqual(len(review.context["review_rows"]), 1 + len(keys) + 4)
        self.assertContains(review, 'name="nav" value="edit:registration_wait"')

        # Editing from the review comes straight back to it.
        card = keys.index("registration_wait")
        edit = self.press("edit:registration_wait", step="review", **answers)
        self.assertEqual((self.place(edit), edit.context["returning"]), (("questions", card), True))
        back = self.press(
            "next", step="questions", card=card, **{**answers, "registration_wait": "2", "return": "review"}
        )
        self.assertEqual((self.place(back), back.context["returning"]), (("review", 0), False))

        self.assertFalse(FeedbackSubmission.objects.exists())  # nothing saved until Submit
        self.assertEqual(self.press("submit", **answers).status_code, 302)
        self.assertEqual(FeedbackSubmission.objects.get().answers["clinic"]["value"], "ent")

    def test_back_walks_the_steps_in_reverse(self):
        answers = {"uhid": UHID, "clinic": "ent"}
        self.assertEqual(self.place(self.press("back", step="questions", card=2, **answers)), ("questions", 1))
        self.assertEqual(self.place(self.press("back", step="questions", card=0, **answers)), ("details", 0))
        self.assertEqual(self.place(self.press("back", step="details", **answers)), ("identify", 0))

    def test_a_guest_answers_the_guest_details(self):
        details = self.press("guest", step="identify", uhid="12345")
        self.assertEqual(self.place(details), ("details", 0))
        self.assertContains(details, 'name="uhid" value=""')
        self.assertNotContains(details, 'data-question-key="age_group" data-audience="guest" data-required="1" hidden')
        missing = self.press("next", step="details")
        self.assertEqual(missing.context["errors"], dict.fromkeys(("clinic", "age_group", "sex"), "required"))

    def test_changing_the_uhid_from_the_review_comes_back_to_it(self):
        answers = self.answers(self.opd)
        uhid_step = self.press("go:uhid", step="review", uhid=UHID, **answers)
        self.assertEqual((self.place(uhid_step), uhid_step.context["returning"]), (("uhid", 0), True))
        # As a guest, age and sex now need answers first.
        guest = self.press("guest", step="uhid", uhid=UHID, **{**answers, "return": "review"})
        self.assertEqual(self.place(guest), ("details", 0))
        review = self.press(
            "next", step="details", **{**answers, "age_group": "18_30", "sex": "male", "return": "review"}
        )
        self.assertEqual(self.place(review), ("review", 0))

    def test_switching_language_keeps_the_step_and_answers(self):
        page = self.press("lang:kn", step="details", uhid=UHID, clinic="ent", language="en")
        self.assertEqual(self.place(page), ("details", 0))
        self.assertContains(page, 'data-lang="kn"')
        self.assertContains(page, 'name="language" value="kn"')
        self.assertContains(page, 'value="ent" checked')

    def test_moving_between_steps_is_not_rate_limited(self):
        with (
            mock.patch("public_feedback.views.is_ratelimited", return_value=True),
            self.settings(DISABLE_RATELIMIT=False),
        ):
            self.assertEqual(self.press("go:uhid", step="identify").status_code, 200)


class QuestionsJsonTests(PageTestBase):
    def test_default_forms_are_valid(self):
        for form in (self.opd, self.ipd):
            self.assertEqual(question_errors(form.questions), [])
            form.full_clean()

    def test_problems_name_the_question(self):
        problems = question_errors(
            [
                {"key": "clinic", "type": "choice", "text": {"en": "Clinic"}, "options": []},
                {"key": "clinic", "type": "text", "text": {"en": "Again"}},
                {"key": "Bad Key", "type": "text", "text": {"en": "Q"}},
                {"key": "wait", "type": "rating", "text": {"en": "Wait"}, "options": [{"en": "a"}]},
                {"key": "visit", "type": "date", "text": {"kn": "ದಿನಾಂಕ"}, "requried": True},
                {"key": "mood", "type": "smiley", "text": {"en": "Mood"}},
                {"key": "why", "type": "boolean", "text": {"en": "Why"}, "required": "yes"},
            ]
        )
        expected = [
            "“clinic”: a choice needs options",
            "“clinic”: another question already uses this key",
            "“Bad Key”: key must be lowercase",
            "“wait”: give exactly five labels",
            "“visit”: unknown field(s) requried",
            "“visit”: text needs the English question",
            "“mood”: type must be one of",
            "“why”: required must be true or false",
        ]
        for start in expected:
            self.assertTrue(any(p.startswith(start) for p in problems), (start, problems))
        self.assertEqual(question_errors({"key": "x"}), ["The questions must be a list: [ {…}, {…} ]."])

    def test_old_answers_keep_their_wording_when_the_form_changes(self):
        self.submit(uhid=UHID, **self.answers(self.opd, 4))
        for question in self.opd.questions:
            if question["key"] == "registration_wait":
                question["text"] = {"en": "How long did you wait to register?"}
        self.opd.questions = [q for q in self.opd.questions if q["key"] != "staff_behaviour"]
        self.opd.save()
        answers = FeedbackSubmission.objects.get().answers
        self.assertEqual(answers["registration_wait"]["question"], "Waiting time at the registration counter")
        self.assertEqual(answers["staff_behaviour"]["question"], "Behaviour and attitude of the hospital staff")

    def test_a_form_with_feedback_cant_be_deleted(self):
        self.submit(uhid=UHID, **self.answers(self.opd))
        with self.assertRaises(ProtectedError):
            self.opd.delete()
        self.ipd.delete()  # no feedback yet: fine
