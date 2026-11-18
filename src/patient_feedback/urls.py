"""API routes; Care mounts this module at /api/patient_feedback/."""

from django.urls import path

from patient_feedback.api import FacilityFeedbackListView, FacilityFeedbackSummaryView, health

app_name = "patient_feedback_api"

urlpatterns = [
    path("health", health, name="health"),
    path(
        "facility/<uuid:facility_external_id>/responses/",
        FacilityFeedbackListView.as_view(),
        name="facility-responses",
    ),
    path(
        "facility/<uuid:facility_external_id>/summary/",
        FacilityFeedbackSummaryView.as_view(),
        name="facility-summary",
    ),
]
