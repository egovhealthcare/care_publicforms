from typing import Any

import environ
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver
from rest_framework.settings import perform_import

from patient_feedback.apps import PLUGIN_NAME

env = environ.Env()


class PluginSettings:  # pragma: no cover
    """
    A settings object that allows plugin settings to be accessed as
    properties. For example:

        from patient_feedback.settings import plugin_settings
        print(plugin_settings.UHID_LENGTH)

    Values are resolved from (in order) the plug config in care's
    ``plug_config.py`` (``PLUGIN_CONFIGS``), environment variables, and the
    defaults below.
    """

    def __init__(
        self,
        plugin_name: str = None,
        defaults: dict | None = None,
        import_strings: set | None = None,
        required_settings: set | None = None,
    ) -> None:
        if not plugin_name:
            raise ValueError("Plugin name must be provided")
        self.plugin_name = plugin_name
        self.defaults = defaults or {}
        self.import_strings = import_strings or set()
        self.required_settings = required_settings or set()
        self._cached_attrs = set()
        self.validate()

    def __getattr__(self, attr) -> Any:
        if attr not in self.defaults:
            raise AttributeError(f"Invalid setting: '{attr}'")

        val = self.defaults[attr]
        try:
            val = self.user_settings[attr]
        except KeyError:
            try:
                val = env(attr, cast=type(val))
            except environ.ImproperlyConfigured:
                pass

        if attr in self.import_strings:
            val = perform_import(val, attr)

        self._cached_attrs.add(attr)
        setattr(self, attr, val)
        return val

    @property
    def user_settings(self) -> dict:
        if not hasattr(self, "_user_settings"):
            self._user_settings = getattr(settings, "PLUGIN_CONFIGS", {}).get(self.plugin_name, {})
        return self._user_settings

    def validate(self) -> None:
        for setting in self.required_settings:
            if not getattr(self, setting):
                raise ImproperlyConfigured(
                    f'The "{setting}" setting is required. '
                    f'Please set the "{setting}" in the environment or the {PLUGIN_NAME} plugin config.'
                )

    def reload(self) -> None:
        for attr in self._cached_attrs:
            delattr(self, attr)
        self._cached_attrs.clear()
        if hasattr(self, "_user_settings"):
            delattr(self, "_user_settings")


REQUIRED_SETTINGS = set()

DEFAULTS = {
    # Number of digits in a UHID (the number printed on the OP slip).
    "UHID_LENGTH": 11,
    # How the UHID is grouped on screen, e.g. 3-4-4 → "123 4567 8901".
    # Must add up to UHID_LENGTH.
    "UHID_GROUPS": [3, 4, 4],
    # Prefix of the reference number shown after submitting (OPD-20261118-4821).
    "REFERENCE_PREFIX": "OPD",
    # Seconds without a touch before the kiosk warns, then wipes an unfinished
    # questionnaire and returns to the start screen (browser-side timer).
    "IDLE_TIMEOUT_SECONDS": 90,
    # Server-side backstop: a draft untouched (no page request) for this long
    # is discarded, so kiosks without working JavaScript never carry one
    # patient's answers over to the next. Keep it well above
    # IDLE_TIMEOUT_SECONDS: typing a comment doesn't reach the server.
    "DRAFT_EXPIRY_SECONDS": 600,
    # Seconds the "Thank you" screen stays up before returning to the start.
    "DONE_TIMEOUT_SECONDS": 20,
    # How far back to look for the patient's encounter at the kiosk's facility
    # when linking a UHID response to an encounter. 0 disables linking.
    "ENCOUNTER_LOOKBACK_DAYS": 1,
    # Load DM Sans / Noto Sans Kannada from Google Fonts. Turn off for kiosks
    # without internet access (system fonts are used instead).
    "LOAD_WEB_FONTS": True,
    # Lifetime of the cookie that marks a browser as an authorised kiosk.
    # Browsers cap cookie lifetimes at 400 days.
    "KIOSK_COOKIE_MAX_AGE_DAYS": 400,
}

plugin_settings = PluginSettings(PLUGIN_NAME, defaults=DEFAULTS, required_settings=REQUIRED_SETTINGS)


@receiver(setting_changed)
def reload_plugin_settings(*args, **kwargs) -> None:
    setting = kwargs["setting"]
    if setting == "PLUGIN_CONFIGS":
        plugin_settings.reload()
