import uuid
from datetime import timedelta
from unittest import mock

from care.utils.tests.base import CareAPITestBase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.http import urlencode

from patient_feedback.checks import check_languages
from patient_feedback.models import Audience, FeedbackForm, FeedbackQuestion, FeedbackSubmission, QuestionType
from patient_feedback.questionnaire import FormSpec, applies
from patient_feedback.tests import PLAIN_STATIC_STORAGES, PLUGIN_DEFAULTS

UHID = "12345678901"


@override_settings(STORAGES=PLAIN_STATIC_STORAGES, PLUGIN_CONFIGS=PLUGIN_DEFAULTS)
class PageTestBase(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.facility = self.create_facility(user=self.create_user(), name="District Hospital, Mysuru")
        # Seeded by the 0002 data migration
        self.opd = FeedbackForm.objects.get(code="opd", facility__isnull=True)
        self.ipd = FeedbackForm.objects.get(code="ipd", facility__isnull=True)

    def url(self, name="start", form=None, facility=None, **query):
        kwargs = {"facility_id": (facility or self.facility).external_id}
        if form:
            kwargs["form"] = form
        url = reverse(f"patient_feedback:{name}", kwargs=kwargs)
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

    def answers(self, form, value=5, identified=True):
        """Every required answer, as a complete submission sends them."""
        return {**self.details(form, identified), **self.ratings(form, value, identified)}

    def submit(self, form="opd", **data):
        return self.client.post(self.url("form", form), data)


class PublicPageTests(PageTestBase):
    def test_pages_live_under_the_facility(self):
        base = f"/facility/{self.facility.external_id}"
        self.assertEqual(self.url(), f"{base}/patient_feedback/")
        self.assertEqual(self.url("form", "ipd"), f"{base}/type/ipd/patient_feedback/")
        self.assertEqual(self.url("done", "ipd"), f"{base}/type/ipd/patient_feedback/done/")
        # Typed without the trailing slash
        self.assertRedirects(
            self.client.get(f"{base}/type/ipd/patient_feedback"),
            f"{base}/type/ipd/patient_feedback/",
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
            (submission.facility_external_id, submission.form_code, submission.patient_type, submission.language),
            (self.facility.external_id, "opd", "op", "kn"),
        )
        self.assertEqual(
            submission.answers,
            {
                **self.ratings(self.opd, 4),
                "clinic": "ent",
                "would_return": True,
                "would_return__comment": "Friendly staff",
            },
        )

    def test_submission_table_has_no_relations(self):
        fields = FeedbackSubmission._meta.get_fields()
        self.assertFalse([f.name for f in fields if f.is_relation])
        self.assertEqual(
            {f.name for f in fields},
            {
                "id",
                "external_id",
                "reference_number",
                "facility_external_id",
                "form_code",
                "patient_type",
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
        self.assertEqual(submission.answers["age_group"], "31_45")
        self.assertEqual(submission.answers["sex"], "female")
        self.assertEqual(submission.language, "en")

    def test_missing_ratings_show_the_page_again(self):
        ratings = self.ratings(self.opd)
        first_missing = list(ratings)[2]
        del ratings[first_missing]
        response = self.submit(uhid=UHID, clinic="ent", **ratings)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FeedbackSubmission.objects.exists())
        self.assertEqual(response.context["errors"], {first_missing: "required"})
        self.assertEqual((response.context["start_step"], response.context["start_card"]), ("questions", 2))
        self.assertEqual(response.context["banner"], "error_summary")
        # What was entered is kept.
        self.assertContains(response, f'value="{UHID}"')
        self.assertContains(response, 'value="ent" checked')

    def test_bad_uhid_opens_the_uhid_step(self):
        response = self.submit(uhid="123", **self.ratings(self.opd))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_step"], "uhid")
        self.assertFalse(FeedbackSubmission.objects.exists())

    def test_details_need_answers(self):
        guest = self.submit(**self.ratings(self.opd, identified=False))
        self.assertEqual(guest.context["errors"], dict.fromkeys(("clinic", "age_group", "sex"), "required"))
        self.assertEqual(guest.context["start_step"], "details")
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
        self.assertEqual(FeedbackSubmission.objects.get().answers, self.answers(self.ipd))

    def test_why_without_yes_or_no_is_dropped(self):
        self.submit(uhid=UHID, would_return__comment="Kind staff", **self.answers(self.opd))
        self.assertNotIn("would_return__comment", FeedbackSubmission.objects.get().answers)

    def test_reference_number_uses_the_form_code(self):
        self.submit(uhid=UHID, **self.answers(self.opd))
        reference = FeedbackSubmission.objects.get().reference_number
        self.assertRegex(reference, rf"^OPD-{timezone.localdate():%Y%m%d}-\d{{4}}$")

    @override_settings(PLUGIN_CONFIGS={"patient_feedback": {"REFERENCE_PREFIX": "PF"}})
    def test_reference_prefix_setting(self):
        self.submit("ipd", **self.answers(self.ipd, identified=False))
        self.assertTrue(FeedbackSubmission.objects.get().reference_number.startswith("PF-"))

    def test_long_form_code_still_fits_the_reference(self):
        long_form = FeedbackForm.objects.create(
            code="general_medicine_ward_feedback", patient_type="ip", title={"en": "Ward"}
        )
        FeedbackQuestion.objects.create(form=long_form, key="care", type=QuestionType.RATING, text={"en": "Care"})
        self.assertEqual(self.submit(long_form.code, care="4").status_code, 302)
        reference = FeedbackSubmission.objects.get().reference_number
        self.assertTrue(reference.startswith("GENERAL_MEDI-"))
        self.assertLessEqual(len(reference), FeedbackSubmission._meta.get_field("reference_number").max_length)

    def test_reference_collisions_are_retried(self):
        with mock.patch("patient_feedback.services.secrets.randbelow", side_effect=[1111, 1111, 2222]):
            self.submit(uhid=UHID, **self.answers(self.opd))
            self.submit(uhid=UHID, **self.answers(self.opd))
        numbers = sorted(FeedbackSubmission.objects.values_list("reference_number", flat=True))
        self.assertEqual([n[-4:] for n in numbers], ["2111", "3222"])

    def test_rate_limited(self):
        with (
            mock.patch("patient_feedback.views.is_ratelimited", return_value=True),
            self.settings(DISABLE_RATELIMIT=False),
        ):
            response = self.submit(uhid=UHID, **self.answers(self.opd))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.context["banner"], "too_many")
        # Answers are kept and the page opens on the review, ready to submit again.
        self.assertEqual(response.context["start_step"], "review")
        self.assertFalse(FeedbackSubmission.objects.exists())

    @override_settings(DISABLE_RATELIMIT=False, PLUGIN_CONFIGS={"patient_feedback": {"SUBMIT_RATE_LIMIT": ""}})
    def test_empty_rate_limit_turns_it_off(self):
        with mock.patch("patient_feedback.views.is_ratelimited", return_value=True):
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
    def add_question(self, form, key, **fields):
        return FeedbackQuestion.objects.create(form=form, key=key, text={"en": key.title()}, **fields)

    def test_switching_off_a_facility_form_hides_the_code(self):
        FeedbackForm.objects.create(
            facility=self.facility, code="opd", patient_type="op", title={"en": "Our OPD"}, is_active=False
        )
        self.assertRedirects(self.client.get(self.url()), self.url("form", "ipd"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(self.url("form", "opd")), self.url(), fetch_redirect_response=False)

    def test_facility_form_replaces_the_shared_one(self):
        own = FeedbackForm.objects.create(
            facility=self.facility, code="opd", patient_type="op", title={"en": "Our OPD"}, order=1
        )
        self.add_question(own, "cleanliness", type=QuestionType.RATING)
        page = self.client.get(self.url("form", "opd"))
        self.assertContains(page, "data-card", count=1)
        self.assertContains(page, "Our OPD")
        self.submit(cleanliness="5")
        self.assertEqual(FeedbackSubmission.objects.get().answers, {"cleanliness": 5})
        # Other facilities keep the shared form.
        elsewhere = self.create_facility(user=self.create_user())
        self.assertContains(
            self.client.get(self.url("form", "opd", facility=elsewhere)),
            "data-card",
            count=len(FormSpec(self.opd).ratings),
        )

    def test_inactive_and_new_questions(self):
        dropped = self.opd.questions.filter(type=QuestionType.RATING).first()
        dropped.is_active = False
        dropped.save()
        self.add_question(self.opd, "parking", type=QuestionType.TEXT, required=True, order=999)
        page = self.client.get(self.url("form", "opd"))
        self.assertNotContains(page, f'name="{dropped.key}"')
        self.assertContains(page, 'name="parking"')
        response = self.submit(uhid=UHID, **self.answers(self.opd))
        self.assertEqual(response.context["errors"], {"parking": "required"})
        self.assertEqual(response.context["start_step"], "comments")
        self.submit(uhid=UHID, parking="Inside", **self.answers(self.opd))
        self.assertEqual(FeedbackSubmission.objects.get().answers["parking"], "Inside")

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
        # Without JavaScript the toggle reloads the page in the other language, keeping its parameters.
        self.assertContains(page, f'href="{escape("?from=start&language=en")}"')
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

    @override_settings(PLUGIN_CONFIGS={"patient_feedback": {"LANGUAGES": ["en"]}})
    def test_one_language_hides_the_toggle(self):
        page = self.client.get(self.url("form", "opd"))
        self.assertNotContains(page, 'class="langtog"')
        self.assertNotContains(page, "l10n--kn")
        self.assertNotContains(page, "Noto")
        self.assertContains(page, 'class="l10n l10n--en"')
        self.assertContains(self.client.get(self.url("form", "opd", lang="kn")), 'data-lang="en"')

    @override_settings(PLUGIN_CONFIGS={"patient_feedback": {"LANGUAGES": ["kn", "en", "xx"], "DEFAULT_LANGUAGE": "kn"}})
    def test_order_default_and_unknown_codes(self):
        page = self.client.get(self.url("form", "opd"))
        content = page.content.decode()
        self.assertContains(page, 'data-lang="kn"')
        self.assertLess(content.index('data-set-lang="kn"'), content.index('data-set-lang="en"'))
        self.assertNotContains(page, "xx")
        self.assertEqual([w.id for w in check_languages(None)], ["patient_feedback.W001"])

    @override_settings(PLUGIN_CONFIGS={"patient_feedback": {"LANGUAGES": ["en"], "DEFAULT_LANGUAGE": "kn"}})
    def test_default_language_must_be_offered(self):
        self.assertContains(self.client.get(self.url("form", "opd")), 'data-lang="en"')
        self.assertEqual([w.id for w in check_languages(None)], ["patient_feedback.W002"])

    def test_defaults_raise_no_warnings(self):
        self.assertEqual(check_languages(None), [])
