from importlib import import_module

from django.apps import AppConfig
from django.conf import settings
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

PLUGIN_NAME = "patient_feedback"


class PatientFeedbackConfig(AppConfig):
    name = PLUGIN_NAME
    verbose_name = _("Patient Feedback")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Care mounts `<plugin>.urls` under /api/<plugin>/ for API routes.
        # The kiosk pages are server-rendered HTML, so they live outside /api/,
        # scoped to the facility like Care's own facility routes.
        urlconf = import_module(settings.ROOT_URLCONF)
        urlconf.urlpatterns += [
            path(f"facility/<uuid:facility_id>/{PLUGIN_NAME}/", include(f"{PLUGIN_NAME}.pages")),
        ]
