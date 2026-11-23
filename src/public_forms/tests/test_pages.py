import importlib
import uuid
from datetime import timedelta
from unittest import mock

from care.utils.tests.base import CareAPITestBase
from django.db.models import ProtectedError
from django.templatetags.static import static
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.http import urlencode

from public_forms.checks import check_languages
from public_forms.models import Audience, FeedbackForm, FeedbackSubmission, QuestionType
from public_forms.questionnaire import FormSpec, applies
from public_forms.questions import question_errors, with_steps
from public_forms.tests import PLAIN_STATIC_STORAGES, TEST_LANGUAGE, TEST_PLUGIN_CONFIGS, plugin_configs
from public_forms.views import no_js_countdown

UHID = "12345678901"


@override_settings(STORAGES=PLAIN_STATIC_STORAGES, PLUGIN_CONFIGS=TEST_PLUGIN_CONFIGS)
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
        url = reverse(f"public_forms:{name}", kwargs=kwargs)
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
        self.assertEqual(self.url(), f"{base}/public_forms/")
        self.assertEqual(self.url("form", "ipd"), f"{base}/public_forms/type/ipd/form/")
        self.assertEqual(self.url("done", "ipd"), f"{base}/public_forms/type/ipd/done/")
        # Typed without the trailing slash
        self.assertRedirects(
            self.client.get(f"{base}/public_forms/type/ipd/form"),
            f"{base}/public_forms/type/ipd/form/",
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

    def test_pages_carry_cares_favicon(self):
        icon = f'<link rel="icon" href="{static("public_forms/favicon.ico")}">'
        self.assertContains(self.client.get(self.url()), icon, html=True)
        self.assertContains(self.client.get(self.url("form", "opd")), icon, html=True)
        not_found = self.client.get(self.url(facility=mock.Mock(external_id=uuid.uuid4())))
        self.assertContains(not_found, icon, status_code=404, html=True)

    def test_unknown_form_goes_to_the_chooser(self):
        self.assertRedirects(self.client.get(self.url("form", "nope")), self.url(), fetch_redirect_response=False)

    def test_form_page_holds_every_step_and_language(self):
        response = self.client.get(self.url("form", "opd"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(dict(response.cookies), {})
        for step in ("identify", "scan", "uhid", "details", "questions", "comments", "review"):
            self.assertContains(response, f'data-step="{step}"')
        self.assertContains(response, "data-card", count=len(FormSpec(self.opd).ratings))
        self.assertContains(response, f'class="l10n l10n--{TEST_LANGUAGE}"')
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

    def test_home_and_reset_ask_first(self):
        # kiosk.js opens these cards once Home or Reset would clear answers.
        page = self.client.get(self.url("form", "opd"))
        self.assertContains(page, '<div class="idle confirm" id="confirmHome" hidden>')
        self.assertContains(page, '<div class="idle confirm" id="confirmReset" hidden>')
        for text in ("Leave this feedback?", "Clear your answers?", "Yes, go to home", "Yes, clear them"):
            self.assertContains(page, text)
        self.assertContains(page, "data-confirm-keep", count=2)  # "No, keep my answers" on each card

    def test_screen_options_in_the_url(self):
        response = self.client.get(self.url(lang=TEST_LANGUAGE, scan="off", keypad="0"))
        self.assertContains(response, f'data-lang="{TEST_LANGUAGE}"')
        link = self.url("form", "opd", lang=TEST_LANGUAGE, scan="off", keypad="0", **{"from": "start"})
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
            language=TEST_LANGUAGE,
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
            self.url("done", "opd", ref=submission.reference_number, language=TEST_LANGUAGE),
            fetch_redirect_response=False,
        )
        self.assertEqual(submission.uhid, UHID)
        self.assertEqual(
            (submission.facility_external_id, submission.form, submission.language),
            (self.facility.external_id, self.opd, TEST_LANGUAGE),
        )
        self.assertEqual(
            self.values(submission.answers),
            {**self.ratings(self.opd, 4), "clinic": "ent", "would_return": "yes"},
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
                "type": "choice",
                "value": "yes",
                "answer": "Yes",
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

    @override_settings(PLUGIN_CONFIGS=plugin_configs(REFERENCE_PREFIX="PF"))
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
        with mock.patch("public_forms.services.secrets.randbelow", side_effect=[1111, 1111, 2222]):
            self.submit(uhid=UHID, **self.answers(self.opd))
            self.submit(uhid=UHID, **self.answers(self.opd))
        numbers = sorted(FeedbackSubmission.objects.values_list("reference_number", flat=True))
        self.assertEqual([n[-4:] for n in numbers], ["2111", "3222"])

    def test_rate_limited(self):
        with (
            mock.patch("public_forms.views.is_ratelimited", return_value=True),
            self.settings(DISABLE_RATELIMIT=False),
        ):
            response = self.submit(uhid=UHID, **self.answers(self.opd))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.context["banner"], "too_many")
        # Answers are kept and the page opens on the review, ready to submit again.
        self.assertEqual(response.context["current_step"], "review")
        self.assertFalse(FeedbackSubmission.objects.exists())

    @override_settings(DISABLE_RATELIMIT=False, PLUGIN_CONFIGS=plugin_configs(SUBMIT_RATE_LIMIT=""))
    def test_empty_rate_limit_turns_it_off(self):
        with mock.patch("public_forms.views.is_ratelimited", return_value=True):
            self.assertEqual(self.submit(uhid=UHID, **self.answers(self.opd)).status_code, 302)

    def test_idle_timer_starts_at_once_on_a_patients_page(self):
        armed, unarmed = 'data-idle-armed="1"', 'data-idle-armed="0"'
        self.assertContains(self.client.get(self.url("form", "opd")), unarmed)  # fresh screen
        self.assertContains(self.client.get(self.url()), unarmed)
        self.assertContains(self.client.get(self.url(language=TEST_LANGUAGE)), armed)  # their language
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

    def test_back_cannot_return_to_it_later(self):
        # The screen is shared: once the thank-you page has had its time, Back
        # (or the browser's history) goes to the start, not to the previous
        # patient's reference number.
        response, submission = self.done_page()
        self.assertIn("no-store", response["Cache-Control"])  # Back asks the server again
        self.assertContains(response, "data-replace")  # "Start new" replaces it in the history
        FeedbackSubmission.objects.filter(pk=submission.pk).update(
            submitted_at=timezone.now() - timedelta(seconds=20 + 10 + 1)
        )
        self.assertRedirects(
            self.client.get(self.url("done", "opd", ref=submission.reference_number)),
            self.url("form", "opd"),
            fetch_redirect_response=False,
        )

    def test_kiosk_pages_are_never_cached(self):
        for response in (self.client.get(self.url()), self.client.get(self.url("form", "opd"))):
            self.assertIn("no-store", response["Cache-Control"])

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
        chooser = self.client.get(self.url(language=TEST_LANGUAGE))
        self.assertContains(chooser, f'data-lang="{TEST_LANGUAGE}"')
        self.assertContains(chooser, escape(self.url("form", "opd", **start, language=TEST_LANGUAGE)))
        self.assertContains(chooser, f'data-home-url="{self.url()}"')
        # The form opens in it, and Back / Home / Reset keep it.
        page = self.client.get(self.url("form", "opd", **start, language=TEST_LANGUAGE))
        self.assertContains(page, f'data-lang="{TEST_LANGUAGE}"')
        self.assertContains(page, f'name="language" value="{TEST_LANGUAGE}"')
        self.assertContains(page, f'href="{self.url(language=TEST_LANGUAGE)}" data-carry-lang', count=2)  # Back, Home
        self.assertContains(
            page, escape(self.url("form", "opd", **start, language=TEST_LANGUAGE)) + '" data-action="reset"'
        )
        # Without JavaScript the toggle posts the form, so the answers stay; on the chooser it is a link.
        self.assertContains(page, 'form="feedback" name="nav" value="lang:en"')
        self.assertContains(chooser, 'href="?language=en"')
        # The idle reset is for the next patient: the screen's own language.
        self.assertContains(page, f'data-home-url="{self.url()}"')
        # Submitted in it, the thank-you page stays in it; its return does not.
        response = self.client.post(
            page.request["PATH_INFO"] + "?" + page.request["QUERY_STRING"],
            {"uhid": UHID, "language": TEST_LANGUAGE, **start, **self.answers(self.opd)},
        )
        self.assertEqual(FeedbackSubmission.objects.get().language, TEST_LANGUAGE)
        done = self.client.get(response["Location"])
        self.assertContains(done, f'data-lang="{TEST_LANGUAGE}"')
        self.assertContains(done, f'content="20;url={self.url()}"')

    def test_patient_language_and_screen_language(self):
        # A screen in the test language where the patient switched to English.
        chooser = self.client.get(self.url(lang=TEST_LANGUAGE, language="en"))
        self.assertContains(chooser, 'data-lang="en"')
        self.assertContains(
            chooser, escape(self.url("form", "opd", lang=TEST_LANGUAGE, **{"from": "start"}, language="en"))
        )
        self.assertContains(chooser, f'data-home-url="{self.url(lang=TEST_LANGUAGE)}"')

    @override_settings(PLUGIN_CONFIGS=plugin_configs(LANGUAGES=["en"]))
    def test_one_language_hides_the_toggle(self):
        page = self.client.get(self.url("form", "opd"))
        self.assertNotContains(page, 'class="langtog"')
        self.assertNotContains(page, f"l10n--{TEST_LANGUAGE}")
        self.assertNotContains(page, "Noto")
        self.assertContains(page, 'class="l10n l10n--en"')
        self.assertContains(self.client.get(self.url("form", "opd", lang=TEST_LANGUAGE)), 'data-lang="en"')

    @override_settings(
        PLUGIN_CONFIGS=plugin_configs(LANGUAGES=[TEST_LANGUAGE, "en", "zz"], DEFAULT_LANGUAGE=TEST_LANGUAGE)
    )
    def test_order_default_and_unknown_codes(self):
        page = self.client.get(self.url("form", "opd"))
        content = page.content.decode()
        self.assertContains(page, f'data-lang="{TEST_LANGUAGE}"')
        self.assertLess(content.index(f'data-set-lang="{TEST_LANGUAGE}"'), content.index('data-set-lang="en"'))
        self.assertNotContains(page, 'data-set-lang="zz"')  # no locale file: not offered
        self.assertNotContains(page, "l10n--zz")
        self.assertEqual([w.id for w in check_languages(None)], ["public_forms.W001"])

    @override_settings(PLUGIN_CONFIGS=plugin_configs(LANGUAGES=["en"], DEFAULT_LANGUAGE=TEST_LANGUAGE))
    def test_default_language_must_be_offered(self):
        self.assertContains(self.client.get(self.url("form", "opd")), 'data-lang="en"')
        self.assertEqual([w.id for w in check_languages(None)], ["public_forms.W002"])

    def test_complete_languages_raise_no_warnings(self):
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
        # Its step offers only the way back to the review: no "Back" to the previous question.
        self.assertContains(edit, 'autocomplete="off" class="is-editing"')
        self.assertContains(edit, 'data-nav="back" data-edit-hidden')
        self.assertNotContains(review, 'class="is-editing"')
        back = self.press(
            "next", step="questions", card=card, **{**answers, "registration_wait": "2", "return": "review"}
        )
        self.assertEqual((self.place(back), back.context["returning"]), (("review", 0), False))

        self.assertFalse(FeedbackSubmission.objects.exists())  # nothing saved until Submit
        self.assertEqual(self.press("submit", **answers).status_code, 302)
        self.assertEqual(FeedbackSubmission.objects.get().answers["clinic"]["value"], "ent")

    def test_changing_the_uhid_mid_way_keeps_the_answers_and_the_place(self):
        keys = list(self.ratings(self.opd))
        answers = {"uhid": UHID, "clinic": "ent", **{key: "4" for key in keys[:4]}}
        # On the fifth rating, the patient taps the UHID strip.
        uhid_step = self.press("go:uhid", step="questions", card=4, **answers)
        self.assertEqual(self.place(uhid_step), ("uhid", 0))
        self.assertContains(uhid_step, 'name="return" value="questions:4"')
        left_at = {**answers, "return": "questions:4"}

        # Another UHID: straight back to the fifth rating, every answer kept.
        other = self.press("uhid", step="uhid", **{**left_at, "uhid": "10987654321"})
        self.assertEqual((self.place(other), other.context["return_to"]), (("questions", 4), ""))
        self.assertContains(other, f'name="{keys[0]}" value="4" checked')
        self.assertContains(other, 'name="clinic" value="ent" checked')

        # A guest: first the guest-only details (age and sex), then the fifth rating.
        guest = self.press("guest", step="uhid", **left_at)
        self.assertEqual((self.place(guest), guest.context["return_to"]), (("details", 0), "questions:4"))
        self.assertNotContains(guest, 'class="is-editing"')  # Back still shows here
        self.assertContains(guest, f'name="{keys[3]}" value="4" checked')
        details = {**left_at, "uhid": "", "age_group": "31_45", "sex": "female"}
        onward = self.press("next", step="details", **details)
        self.assertEqual((self.place(onward), onward.context["return_to"]), (("questions", 4), ""))

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
        page = self.press(f"lang:{TEST_LANGUAGE}", step="details", uhid=UHID, clinic="ent", language="en")
        self.assertEqual(self.place(page), ("details", 0))
        self.assertContains(page, f'data-lang="{TEST_LANGUAGE}"')
        self.assertContains(page, f'name="language" value="{TEST_LANGUAGE}"')
        self.assertContains(page, 'value="ent" checked')

    def test_moving_between_steps_is_not_rate_limited(self):
        with (
            mock.patch("public_forms.views.is_ratelimited", return_value=True),
            self.settings(DISABLE_RATELIMIT=False),
        ):
            self.assertEqual(self.press("go:uhid", step="identify").status_code, 200)


class QuestionsJsonTests(PageTestBase):
    def test_text_rules_apply_to_every_text(self):
        problems = question_errors(
            [
                {
                    "key": "clinic",
                    "type": "choice",
                    "text": {"en": "Clinic <b>visited</b>"},
                    "short_text": {"en": "x" * 61},
                    "hint": {TEST_LANGUAGE: "Pick {one}"},
                    "options": [{"value": "a<b", "en": "ENT"}, {"value": "dental", "en": "Dental `x`" + "y" * 100}],
                }
            ]
        )
        self.assertEqual(
            problems,
            [
                "“clinic”: text (en) can't contain < >.",
                "“clinic”: short_text (en) is longer than 60 characters.",
                f"“clinic”: hint ({TEST_LANGUAGE}) can't contain {{ }}.",
                "“clinic”: option 1's value can't contain <.",
                "“clinic”: option 2 (en) can't contain `.",
                "“clinic”: option 2 (en) is longer than 100 characters.",
            ],
        )

    def test_every_question_says_its_step(self):
        # The default forms, and forms saved before steps were written in (0004).
        for form in (self.opd, self.ipd):
            self.assertTrue(all("step" in question for question in form.questions), form.code)
        migration = importlib.import_module("public_forms.migrations.0004_explicit_question_steps")
        old = [
            {"key": "a", "type": "choice", "text": {"en": "A"}, "options": [{"value": "x", "en": "X"}]},
            {"key": "b", "type": "rating", "text": {"en": "B"}},
            {"key": "c", "type": "text", "text": {"en": "C"}},
            {"key": "d", "type": "date", "text": {"en": "D"}},
            {"key": "e", "type": "choice", "step": "open", "text": {"en": "E"}, "options": [{"value": "y", "en": "Y"}]},
        ]
        new = migration.with_steps(old)
        self.assertEqual([q["step"] for q in new], ["details", "ratings", "open", "details", "open"])
        self.assertEqual(list(new[0])[:3], ["key", "type", "step"])  # written right after the type
        self.assertEqual(new, with_steps(old))  # the admin writes the same on save

    def test_step_decides_the_screen(self):
        # A text question can be asked on "A few details" too; its place there follows the list.
        self.opd.questions = [
            *self.opd.questions,
            {"key": "doctor_name", "type": "text", "step": "details", "required": True, "text": {"en": "Doctor"}},
        ]
        self.opd.save()
        spec = FormSpec(self.opd)
        self.assertEqual(spec.details[-1].key, "doctor_name")
        self.assertNotIn("doctor_name", [q.key for q in spec.open_questions])
        page = self.client.get(self.url("form", "opd"))
        details = page.content.decode().split('data-step="details"')[1].split('data-step="questions"')[0]
        self.assertIn('<textarea name="doctor_name"', details)
        # It is required there like any details question (without JavaScript, too).
        step = self.client.post(
            self.url("form", "opd"), {"nav": "next", "step": "details", "uhid": UHID, "clinic": "ent"}
        )
        self.assertEqual(step.context["errors"], {"doctor_name": "required"})

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
                {"key": "visit", "type": "date", "text": {TEST_LANGUAGE: "Date"}, "requried": True},
                {"key": "mood", "type": "smiley", "text": {"en": "Mood"}},
                {
                    "key": "why",
                    "type": "choice",
                    "text": {"en": "Why"},
                    "required": "yes",
                    "options": [{"value": "a", "en": "A"}],
                },
                {"key": "stay", "type": "text", "text": {"en": "Stay"}, "step": "details", "allow_comment": True},
                {"key": "card", "type": "rating", "text": {"en": "Card"}, "step": "open"},
                {
                    "key": "back",
                    "type": "choice",
                    "text": {"en": "Back?"},
                    "step": "later",
                    "options": [{"value": "y", "en": "Y"}],
                },
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
            "“stay”: allow_comment (“Why?”) is for choices only",  # a text question may go on details
            '“card”: a rating question is asked on ratings, not "open"',
            '“back”: a choice question is asked on details or open, not "later"',
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

    def test_a_yes_no_question_is_an_open_choice(self):
        page = self.client.get(self.url("form", "opd"))
        spec = FormSpec(self.opd)
        self.assertIn("would_return", [q.key for q in spec.open_questions])
        self.assertNotIn("would_return", [q.key for q in spec.details])
        # Two options on the "in your own words" step: large Yes / No buttons, with "Why?".
        self.assertContains(page, '<input type="radio" name="would_return" value="yes">')
        self.assertContains(page, 'name="would_return__comment"')
        self.submit(uhid=UHID, would_return="no", would_return__comment="Long queue", **self.answers(self.opd))
        self.assertEqual(
            FeedbackSubmission.objects.get().answers["would_return"],
            {
                "question": "Would you come back to this hospital for treatment?",
                "type": "choice",
                "value": "no",
                "answer": "No",
                "comment": "Long queue",
            },
        )


class TypedTextTests(PageTestBase):
    """text_rules: typed text can't hold < > { } ` \\, drops control characters and has a length limit."""

    def test_script_characters_are_refused(self):
        response = self.submit(uhid=UHID, **self.answers(self.opd), improvement="<script>alert(1)</script>")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["errors"], {"improvement": "characters"})
        self.assertEqual(response.context["current_step"], "comments")
        self.assertContains(response, escape("Please don't use these characters: < > { } ` \\"))
        self.assertContains(response, 'maxlength="2000"')
        self.assertContains(response, 'data-blocked-characters="' + escape("<>{}`\\") + '"')
        self.assertFalse(FeedbackSubmission.objects.exists())

    def test_a_why_is_checked_too(self):
        response = self.submit(uhid=UHID, **self.answers(self.opd), would_return="no", would_return__comment="{{7*7}}")
        self.assertEqual(response.context["errors"], {"would_return": "characters"})
        self.assertFalse(FeedbackSubmission.objects.exists())

    def test_everyday_text_is_kept(self):
        text = 'Doctor\'s room & lab (2nd floor) were clean; "thanks"! ಧನ್ಯವಾದಗಳು'
        self.assertEqual(self.submit(uhid=UHID, **self.answers(self.opd), improvement=text).status_code, 302)
        self.assertEqual(FeedbackSubmission.objects.get().answers["improvement"]["value"], text)

    def test_control_characters_are_dropped_and_long_text_is_cut(self):
        self.submit(
            uhid=UHID,
            **self.answers(self.opd),
            improvement="Clean\x00 rooms\x07",
            would_return="yes",
            would_return__comment="a" * 2100,
        )
        answers = FeedbackSubmission.objects.get().answers
        self.assertEqual(answers["improvement"]["value"], "Clean rooms")
        self.assertEqual(len(answers["would_return"]["comment"]), 2000)

    def test_without_javascript_the_step_shows_the_problem(self):
        data = {"uhid": UHID, **self.answers(self.opd), "improvement": "a > b"}
        response = self.client.post(self.url("form", "opd"), {"nav": "next", "step": "comments", **data})
        self.assertEqual(
            (response.context["current_step"], response.context["errors"]), ("comments", {"improvement": "characters"})
        )


class NoJavaScriptIdleTests(PageTestBase):
    """Without JavaScript: start over 3 minutes after the page loaded, counting down in the header."""

    def test_three_minutes_with_a_countdown(self):
        page = self.client.get(self.url("form", "opd", **{"from": "start"}))  # holds the patient's form choice
        self.assertContains(page, f'<noscript><meta http-equiv="refresh" content="180;url={self.url()}"></noscript>')
        self.assertContains(page, 'class="tick-timer" role="timer" style="animation-delay:150s"')
        self.assertContains(page, "animation:tick 240s steps(4) -59s forwards")  # minutes 3 2 1 0
        self.assertContains(page, "animation:tick 60s steps(6) -59s infinite")  # tens of seconds
        self.assertContains(page, "animation:tick 10s steps(10) -9s infinite")  # seconds
        self.assertContains(page, 'data-idle-timeout="90"')  # with JavaScript: as before

    def test_not_on_an_untouched_screen_or_the_thank_you_page(self):
        fresh = self.client.get(self.url("form", "opd"))
        self.assertNotContains(fresh, "tick-timer")
        self.assertNotContains(fresh, 'http-equiv="refresh"')
        response = self.submit(uhid=UHID, **self.answers(self.opd))
        done = self.client.get(response["Location"])
        self.assertNotContains(done, "tick-timer")
        self.assertContains(done, 'http-equiv="refresh"', count=1)  # only its own 20-second return

    @override_settings(PLUGIN_CONFIGS=plugin_configs(NO_JS_IDLE_TIMEOUT_SECONDS=0))
    def test_zero_turns_it_off(self):
        page = self.client.get(self.url("form", "opd", **{"from": "start"}))
        self.assertNotContains(page, "tick-timer")
        self.assertNotContains(page, 'http-equiv="refresh"')

    def test_the_columns_read_the_time_left_every_second(self):
        # What each digit column shows t seconds after the page loaded, from the
        # timing base.html gives it (steps of the CSS animation), against m:ss.
        for seconds in (180, 75, 45, 600, 61):
            timing = no_js_countdown(seconds)
            for t in range(seconds + 1):
                minute = timing["minutes"][(t + timing["minutes_delay"]) // 60]
                tens = "543210"[((t + timing["tens_delay"]) // 10) % 6]
                units = "9876543210"[(t + timing["units_delay"]) % 10]
                left = seconds - t
                self.assertEqual(f"{minute}:{tens}{units}", f"{left // 60}:{left % 60:02d}", (seconds, t))
