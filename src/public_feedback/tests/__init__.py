from django.conf import settings

# Care serves static files through a manifest storage that only knows files
# gathered by `collectstatic` (Care's start scripts run it, so production is
# fine). Tests render templates without that step, so use plain storage.
PLAIN_STATIC_STORAGES = {
    **settings.STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Tests run against the plugin's own defaults, whatever the Care checkout's
# plug_config.py sets for it (languages, prefixes …).
PLUGIN_DEFAULTS = {**getattr(settings, "PLUGIN_CONFIGS", {}), "public_feedback": {}}
