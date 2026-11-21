"""
Kiosk pages (no login, kiosk key, session or cookies), mounted under
/facility/<facility_id>/public_forms/ (see apps.py):

  /facility/<id>/public_forms/                    form chooser
  /facility/<id>/public_forms/type/<form>/form/   one form; POST saves it
  /facility/<id>/public_forms/type/<form>/done/   thank you + reference
"""

from django.urls import path

from public_forms import views

app_name = "public_forms"

urlpatterns = [
    path("", views.StartView.as_view(), name="start"),
    path("type/<slug:form>/form/", views.FormView.as_view(), name="form"),
    path("type/<slug:form>/done/", views.DoneView.as_view(), name="done"),
]
