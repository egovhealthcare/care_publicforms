"""
Public feedback pages (no login, kiosk key, session or cookies), mounted
under /facility/<facility_id>/ (see apps.py):

  /facility/<id>/patient_feedback/                   form chooser
  /facility/<id>/type/<form>/patient_feedback/       one form; POST saves it
  /facility/<id>/type/<form>/patient_feedback/done/  thank you + reference
"""

from django.urls import path

from patient_feedback import views

app_name = "patient_feedback"

urlpatterns = [
    path("patient_feedback/", views.StartView.as_view(), name="start"),
    path("type/<slug:form>/patient_feedback/", views.FormView.as_view(), name="form"),
    path("type/<slug:form>/patient_feedback/done/", views.DoneView.as_view(), name="done"),
]
