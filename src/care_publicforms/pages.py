"""
Kiosk pages (no login, kiosk key, session or cookies), mounted
under /facility/<facility_id>/ (see apps.py):

  /facility/<id>/care_publicforms/                   form chooser
  /facility/<id>/type/<form>/care_publicforms/       one form; POST saves it
  /facility/<id>/type/<form>/care_publicforms/done/  thank you + reference
"""

from django.urls import path

from care_publicforms import views

app_name = "care_publicforms"

urlpatterns = [
    path("care_publicforms/", views.StartView.as_view(), name="start"),
    path("type/<slug:form>/care_publicforms/", views.FormView.as_view(), name="form"),
    path("type/<slug:form>/care_publicforms/done/", views.DoneView.as_view(), name="done"),
]
