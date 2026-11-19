"""
Public feedback pages (no login, kiosk key, session or cookies), mounted
under /facility/<facility_id>/ (see apps.py):

  /facility/<id>/public_feedback/                   form chooser
  /facility/<id>/type/<form>/public_feedback/       one form; POST saves it
  /facility/<id>/type/<form>/public_feedback/done/  thank you + reference
"""

from django.urls import path

from public_feedback import views

app_name = "public_feedback"

urlpatterns = [
    path("public_feedback/", views.StartView.as_view(), name="start"),
    path("type/<slug:form>/public_feedback/", views.FormView.as_view(), name="form"),
    path("type/<slug:form>/public_feedback/done/", views.DoneView.as_view(), name="done"),
]
