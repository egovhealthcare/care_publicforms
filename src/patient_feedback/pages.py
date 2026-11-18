"""Server-rendered kiosk pages, mounted at /patient_feedback/ (see apps.py)."""

from django.urls import path

from patient_feedback import views

app_name = "patient_feedback"

kiosk = "kiosk/<uuid:kiosk_id>/"

urlpatterns = [
    path(kiosk, views.StartView.as_view(), name="start"),
    path(f"{kiosk}scan/", views.ScanView.as_view(), name="scan"),
    path(f"{kiosk}uhid/", views.UhidView.as_view(), name="uhid"),
    path(f"{kiosk}guest/", views.GuestView.as_view(), name="guest"),
    path(f"{kiosk}question/<int:number>/", views.QuestionView.as_view(), name="question"),
    path(f"{kiosk}comments/", views.CommentsView.as_view(), name="comments"),
    path(f"{kiosk}review/", views.ReviewView.as_view(), name="review"),
    path(f"{kiosk}done/", views.DoneView.as_view(), name="done"),
    path(f"{kiosk}reset/", views.ResetView.as_view(), name="reset"),
    path(f"{kiosk}language/<str:code>/", views.LanguageView.as_view(), name="language"),
]
