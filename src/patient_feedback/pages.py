"""
Server-rendered kiosk pages, mounted at /facility/<facility_id>/patient_feedback/
(see apps.py). Every view receives ``facility_id``; which kiosk is asking comes
from its key or cookie (see kiosk_auth.py).

Each step of a form lives under the form's code, e.g. /ipd/, /ipd/questions/.
A kiosk launched on /ipd/ stays on that form (see IdentifyView). The fixed
paths come first, so their names can't be used as form codes.
"""

from django.urls import path

from patient_feedback import views

app_name = "patient_feedback"

urlpatterns = [
    path("", views.StartView.as_view(), name="start"),
    path("done/", views.DoneView.as_view(), name="done"),
    path("reset/", views.ResetView.as_view(), name="reset"),
    path("language/<str:code>/", views.LanguageView.as_view(), name="language"),
    path("<slug:form>/", views.IdentifyView.as_view(), name="identify"),
    path("<slug:form>/scan/", views.ScanView.as_view(), name="scan"),
    path("<slug:form>/uhid/", views.UhidView.as_view(), name="uhid"),
    path("<slug:form>/guest/", views.GuestView.as_view(), name="guest"),
    path("<slug:form>/details/", views.DetailsView.as_view(), name="details"),
    path("<slug:form>/questions/", views.QuestionsView.as_view(), name="questions"),
    path("<slug:form>/comments/", views.CommentsView.as_view(), name="comments"),
    path("<slug:form>/review/", views.ReviewView.as_view(), name="review"),
]
