from datetime import timedelta

from care.utils.tests.base import CareAPITestBase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from patient_feedback.models import FeedbackKiosk, FeedbackResponse
from patient_feedback.questionnaire import QUESTION_KEYS
from patient_feedback.tests import PLAIN_STATIC_STORAGES


class FeedbackApiTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.owner = self.create_user()
        self.facility = self.create_facility(user=self.owner)
        self.kiosk = FeedbackKiosk.objects.create(facility=self.facility, name="OPD")
        self.superuser = self.create_super_user()
        now = timezone.now()
        self.make_response("OPD-1", {key: 5 for key in QUESTION_KEYS}, "manual", True, now)
        self.make_response("OPD-2", {**{key: 3 for key in QUESTION_KEYS}, "waiting_area": 0}, "guest", False, now)
        self.make_response("OPD-3", {key: 1 for key in QUESTION_KEYS}, "guest", None, now - timedelta(days=10))

    def make_response(self, reference, ratings, method, would_return, submitted_at):
        scores = [v for v in ratings.values() if v]
        return FeedbackResponse.objects.create(
            kiosk=self.kiosk,
            facility=self.facility,
            reference_number=reference,
            questionnaire_version="opd-v1",
            language="en",
            identification_method=method,
            ratings=ratings,
            average_rating=sum(scores) / len(scores),
            would_return=would_return,
            submitted_at=submitted_at,
        )

    def url(self, name):
        return reverse(f"patient_feedback_api:{name}", kwargs={"facility_external_id": self.facility.external_id})

    def test_requires_login(self):
        self.assertIn(self.client.get(self.url("facility-summary")).status_code, (401, 403))

    def test_user_without_facility_access_is_denied(self):
        self.client.force_authenticate(self.create_user())
        self.assertEqual(self.client.get(self.url("facility-responses")).status_code, 403)
        self.assertEqual(self.client.get(self.url("facility-summary")).status_code, 403)

    def test_list(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get(self.url("facility-responses"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        first = response.data["results"][0]
        self.assertEqual(first["kiosk"]["name"], "OPD")
        self.assertIn(first["reference_number"], {"OPD-1", "OPD-2"})

        guests = self.client.get(self.url("facility-responses"), {"identification_method": "guest"})
        self.assertEqual(guests.data["count"], 2)

    def test_invalid_filters(self):
        self.client.force_authenticate(self.superuser)
        self.assertEqual(self.client.get(self.url("facility-responses"), {"kiosk": "x"}).status_code, 400)
        self.assertEqual(self.client.get(self.url("facility-summary"), {"submitted_after": "x"}).status_code, 400)

    def test_summary(self):
        self.client.force_authenticate(self.superuser)
        since = (timezone.localdate() - timedelta(days=1)).isoformat()
        data = self.client.get(self.url("facility-summary"), {"submitted_after": since}).data
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["would_return"], {"yes": 1, "no": 1, "unanswered": 0})
        self.assertEqual(data["by_identification"]["guest"], 1)
        waiting = next(q for q in data["questions"] if q["key"] == "waiting_area")
        self.assertEqual(waiting["answered"], 2)
        self.assertEqual(waiting["average"], 5.0)  # "No comments" is not averaged
        self.assertEqual(waiting["distribution"]["0"], 1)
        overall = next(q for q in data["questions"] if q["key"] == "overall_satisfaction")
        self.assertEqual(overall["average"], 4.0)

    def test_health(self):
        self.assertEqual(self.client.get(reverse("patient_feedback_api:health")).status_code, 200)


@override_settings(STORAGES=PLAIN_STATIC_STORAGES)
class AdminTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.superuser = self.create_super_user(is_staff=True)
        self.facility = self.create_facility(user=self.superuser)
        self.kiosk = FeedbackKiosk.objects.create(facility=self.facility, name="OPD")
        self.client.force_login(self.superuser)

    def test_kiosk_change_page_shows_link(self):
        url = reverse("admin:patient_feedback_feedbackkiosk_change", args=[self.kiosk.pk])
        response = self.client.get(url)
        self.assertContains(response, f"?key={self.kiosk.access_key}")

    def test_csv_export_escapes_formulas(self):
        FeedbackResponse.objects.create(
            kiosk=self.kiosk,
            facility=self.facility,
            reference_number="OPD-1",
            questionnaire_version="opd-v1",
            language="en",
            identification_method="guest",
            ratings={"overall_satisfaction": 4},
            suggestions='=HYPERLINK("http://x")',
            submitted_at=timezone.now(),
        )
        response = self.client.post(
            reverse("admin:patient_feedback_feedbackresponse_changelist"),
            {"action": "export_csv", "_selected_action": FeedbackResponse.objects.values_list("pk", flat=True)},
        )
        content = b"".join(response.streaming_content).decode()
        self.assertIn("reference_number", content.splitlines()[0])
        self.assertIn("'=HYPERLINK", content)
