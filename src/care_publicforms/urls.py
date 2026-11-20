"""API routes; Care mounts this module at /api/care_publicforms/."""

from django.urls import path

from care_publicforms.api import FacilityFeedbackListView, FacilityFeedbackSummaryView, health

app_name = "care_publicforms_api"

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
