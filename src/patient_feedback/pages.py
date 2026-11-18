"""
Public feedback pages, mounted at /facility/<facility_id>/patient_feedback/
(see apps.py). No login, kiosk key, session or cookies.
"""

from django.urls import path

from patient_feedback import views

app_name = "patient_feedback"

urlpatterns = [
    path("", views.StartView.as_view(), name="start"),
    path("<slug:form>/", views.FormView.as_view(), name="form"),
    path("<slug:form>/done/", views.DoneView.as_view(), name="done"),
]
