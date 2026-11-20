from importlib import import_module

from django.apps import AppConfig
from django.conf import settings
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

PLUGIN_NAME = "care_publicforms"


class PublicFormsConfig(AppConfig):
    name = PLUGIN_NAME
    verbose_name = _("Public Forms")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import_module(f"{PLUGIN_NAME}.checks")  # registers the settings checks

        # Care mounts `<plugin>.urls` under /api/<plugin>/ for API routes.
        # The feedback pages are server-rendered HTML, so they live outside
        # /api/, scoped to the facility like Care's own facility routes (see
        # pages.py for the paths).
        urlconf = import_module(settings.ROOT_URLCONF)
        urlconf.urlpatterns += [
            path("facility/<uuid:facility_id>/", include(f"{PLUGIN_NAME}.pages")),
        ]
