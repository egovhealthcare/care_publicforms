"""
The admin for feedback forms and submissions. It is its own site, apart from
Django's /admin/, and holds only this plugin's two screens.

It is served on the API host at ADMIN_URL (default /public_forms/admin/).
Signing in is Care's own: the site is built on the admin site Care sets up
for /admin/, so it has Care's sign-in page and rate limits, and asks users
who turned on two-factor authentication for their authenticator code. A
code entered on either admin counts for both.

Care staff users (``is_staff``) can use it if they are superusers or hold
one of this app's permissions (e.g. "Can view feedback submission"). The
permissions say what a user may do; Care's roles say at which facilities
(access.py).
"""

from django.apps import apps
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from public_forms.apps import PLUGIN_NAME
from public_forms.settings import DEFAULTS, plugin_settings

# The admin site class Care uses for /admin/ (CareAdminSite, with its
# two-factor sign-in), or Django's own on Care versions without one.
CareAdminSite = import_string(apps.get_app_config("admin").default_site)


class PublicFormsAdminSite(CareAdminSite):
    site_header = _("Public Forms")
    site_title = _("Public Forms")
    index_title = _("Feedback forms and submissions")
    site_url = None  # no "View site" link: the pages belong to each facility
    # No "Recent actions": its entries link into Django's own /admin/.
    index_template = "public_forms/admin/index.html"

    def has_permission(self, request):
        # Care's check (an active staff user, who entered the code if they
        # turned it on), and at least one of this app's permissions.
        return super().has_permission(request) and request.user.has_module_perms(PLUGIN_NAME)


site = PublicFormsAdminSite(name="public_forms_admin")


def admin_path() -> str:
    """Where the admin is served, e.g. ``"public_forms/admin/"``: ADMIN_URL without slashes at the ends."""
    path = str(plugin_settings.ADMIN_URL or "").strip("/") or DEFAULTS["ADMIN_URL"]
    return f"{path}/"
