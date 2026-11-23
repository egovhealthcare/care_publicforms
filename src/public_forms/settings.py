from typing import Any

import environ
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver
from rest_framework.settings import perform_import

from public_forms.apps import PLUGIN_NAME

env = environ.Env()


class PluginSettings:  # pragma: no cover
    """
    A settings object that allows plugin settings to be accessed as
    properties. For example:

        from public_forms.settings import plugin_settings
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
    # Languages offered in the header toggle, in order. Each needs a locale
    # file, <code>.json (built in: "en", "kn"); one language hides the toggle.
    "LANGUAGES": ["en", "kn"],
    # Extra folders of locale files (<code>.json, see i18n.py), read after the
    # plugin's own: add a language, or correct strings of a built-in one,
    # without changing the plugin. Restart after editing the files.
    "LOCALE_DIRS": [],
    # Language a new patient starts in; one of LANGUAGES (else the first).
    # A screen can start in another one with ?lang=kn in its URL.
    "DEFAULT_LANGUAGE": "en",
    # How the QR on the OP slip is read: "camera" (the browser reads it with
    # the screen's camera), "scanner" (a USB/Bluetooth scanner in keyboard
    # mode) or "off". A screen can override it with ?scan=scanner.
    "SCAN_MODE": "camera",
    # Show an on-screen number pad for the UHID (screens without a system
    # keyboard). A screen can override it with ?keypad=0 or ?keypad=1.
    "SHOW_KEYPAD": True,
    # Number of digits in a UHID (the number printed on the OP slip). Only
    # the format is checked; the UHID is stored as entered.
    "UHID_LENGTH": 11,
    # How the UHID is grouped on screen, e.g. 3-4-4 → "123 4567 8901".
    # Must add up to UHID_LENGTH.
    "UHID_GROUPS": [3, 4, 4],
    # Prefix of the reference number shown after submitting. Empty uses the
    # form's code, e.g. OPD-20261118-4821 / IPD-20261118-0932.
    "REFERENCE_PREFIX": "",
    # Seconds without a touch before the screen warns, then starts over.
    "IDLE_TIMEOUT_SECONDS": 90,
    # Without JavaScript the page can't see touches: it starts over this many
    # seconds after it loaded, counting down in the header. 0 turns it off.
    "NO_JS_IDLE_TIMEOUT_SECONDS": 180,
    # Seconds the "Thank you" screen stays up before starting over.
    "DONE_TIMEOUT_SECONDS": 20,
    # The pages are public, so limit how often one IP address can submit
    # (django-ratelimit rate; Care's DISABLE_RATELIMIT turns it off).
    "SUBMIT_RATE_LIMIT": "60/m",
    # Path of the admin for forms and submissions on the API host. It is
    # its own site, apart from Django's /admin/ (see admin_site.py). Read
    # when Care starts.
    "ADMIN_URL": "public_forms/admin",
    # Sign-in attempts allowed on that admin per IP address, and per
    # username (django-ratelimit rate; Care's DISABLE_RATELIMIT turns it off).
    "ADMIN_LOGIN_RATE_LIMIT": "5/m",
    # Load DM Sans and each language's font (e.g. Noto Sans Kannada) from Google Fonts.
    # Turn off for screens without internet access (system fonts are used).
    "LOAD_WEB_FONTS": True,
}

plugin_settings = PluginSettings(PLUGIN_NAME, defaults=DEFAULTS, required_settings=REQUIRED_SETTINGS)


@receiver(setting_changed)
def reload_plugin_settings(*args, **kwargs) -> None:
    setting = kwargs["setting"]
    if setting == "PLUGIN_CONFIGS":
        plugin_settings.reload()
