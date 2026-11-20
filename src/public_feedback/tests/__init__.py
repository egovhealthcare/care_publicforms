import atexit
import json
import shutil
import tempfile
from pathlib import Path

from django.conf import settings

from public_feedback.i18n import BASE_LANGUAGE, LOCALE_DIR

# Care serves static files through a manifest storage that only knows files
# gathered by `collectstatic` (Care's start scripts run it, so production is
# fine). Tests render templates without that step, so use plain storage.
PLAIN_STATIC_STORAGES = {
    **settings.STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# The tests' second language: made from en.json, so no test depends on which
# languages the plugin ships, and adding or removing one breaks nothing.
TEST_LANGUAGE = "xx"
TEST_LANGUAGE_NAME = "Test language"
TEST_LOCALE_DIR = tempfile.mkdtemp(prefix="public_feedback_locale_")
atexit.register(shutil.rmtree, TEST_LOCALE_DIR, ignore_errors=True)

_english = json.loads((LOCALE_DIR / f"{BASE_LANGUAGE}.json").read_text(encoding="utf-8"))
(Path(TEST_LOCALE_DIR) / f"{TEST_LANGUAGE}.json").write_text(
    json.dumps(
        {
            "language": {"name": TEST_LANGUAGE_NAME, "toggle": "XX", "font": "Noto Sans Test", "tall_script": True},
            "strings": {key: f"xx {text}" for key, text in _english["strings"].items()},
            "ratings": {value: f"xx {text}" for value, text in _english["ratings"].items()},
        }
    ),
    encoding="utf-8",
)


def plugin_configs(**config) -> dict:
    """
    PLUGIN_CONFIGS for a test: English and the test language, whatever the
    Care checkout's plug_config.py sets, with ``config`` on top.
    """
    return {
        **getattr(settings, "PLUGIN_CONFIGS", {}),
        "public_feedback": {"LANGUAGES": [BASE_LANGUAGE, TEST_LANGUAGE], "LOCALE_DIRS": [TEST_LOCALE_DIR], **config},
    }


TEST_PLUGIN_CONFIGS = plugin_configs()
