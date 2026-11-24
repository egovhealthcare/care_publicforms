"""
The admin for feedback forms and submissions. It is its own site, apart from
Django's /admin/, and holds only this plugin's two screens.

It is served on the API host at ADMIN_URL (default /public_forms/admin/).
Care superusers can sign in, and so can any active user given one of this
app's permissions (e.g. "Can view feedback submission"). Those users don't
need Django staff access, so the rest of Django's admin stays closed to
them. The permissions say what a user may do; Care's roles say at which
facilities (access.py). Sign-in attempts are rate-limited per IP address
and per username.
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django_ratelimit.core import is_ratelimited

from public_forms.apps import PLUGIN_NAME
from public_forms.settings import DEFAULTS, plugin_settings


def can_use_admin(user) -> bool:
    """Superusers, and active users with at least one of this app's permissions."""
    return bool(user.is_active and (user.is_superuser or user.has_module_perms(PLUGIN_NAME)))


def login_rate_limited(request) -> bool:
    """Counts this sign-in attempt; True once its IP address or username has had too many."""
    rate = plugin_settings.ADMIN_LOGIN_RATE_LIMIT
    if not rate or getattr(settings, "DISABLE_RATELIMIT", False):
        return False
    by_ip = is_ratelimited(request, group="public_forms.admin_login.ip", key="ip", rate=rate, increment=True)
    by_user = is_ratelimited(
        request, group="public_forms.admin_login.username", key="post:username", rate=rate, increment=True
    )
    return by_ip or by_user


class LoginForm(AdminAuthenticationForm):
    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": _(
            "Enter the username and password of an account that can manage feedback forms. Both are case-sensitive."
        ),
        "too_many": _("Too many sign-in attempts. Wait a minute and try again."),
    }

    def clean(self):
        if self.request is not None and login_rate_limited(self.request):
            raise ValidationError(self.error_messages["too_many"], code="too_many")
        return super().clean()

    def confirm_login_allowed(self, user):
        # Django's admin form asks for staff; this site asks for its own permissions instead.
        if not can_use_admin(user):
            raise self.get_invalid_login_error()


class PublicFormsAdminSite(admin.AdminSite):
    site_header = _("Public Forms")
    site_title = _("Public Forms")
    index_title = _("Feedback forms and submissions")
    site_url = None  # no "View site" link: the pages belong to each facility
    # No "Recent actions": its entries link into Django's own /admin/.
    index_template = "public_forms/admin/index.html"
    login_form = LoginForm

    def has_permission(self, request):
        return can_use_admin(request.user)


site = PublicFormsAdminSite(name="public_forms_admin")


def admin_path() -> str:
    """Where the admin is served, e.g. ``"public_forms/admin/"``: ADMIN_URL without slashes at the ends."""
    path = str(plugin_settings.ADMIN_URL or "").strip("/") or DEFAULTS["ADMIN_URL"]
    return f"{path}/"
