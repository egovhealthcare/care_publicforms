"""
Server-rendered kiosk pages, mounted at /facility/<facility_id>/patient_feedback/
(see apps.py). Every view receives ``facility_id``; which kiosk is asking comes
from its key or cookie (see kiosk_auth.py).
"""

from django.urls import path

from patient_feedback import views

app_name = "patient_feedback"

urlpatterns = [
    path("", views.StartView.as_view(), name="start"),
    path("scan/", views.ScanView.as_view(), name="scan"),
    path("uhid/", views.UhidView.as_view(), name="uhid"),
    path("guest/", views.GuestView.as_view(), name="guest"),
    path("question/<int:number>/", views.QuestionView.as_view(), name="question"),
    path("comments/", views.CommentsView.as_view(), name="comments"),
    path("review/", views.ReviewView.as_view(), name="review"),
    path("done/", views.DoneView.as_view(), name="done"),
    path("reset/", views.ResetView.as_view(), name="reset"),
    path("language/<str:code>/", views.LanguageView.as_view(), name="language"),
]
