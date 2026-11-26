"""
The facilities a user can reach in the admin and the API, by Care's roles.

Django permissions say what an admin user may do (view submissions, change
forms); these say where. They follow Care's own facility checks
(``can_read_facility_questionnaire``, ``can_update_facility_obj``):
a role holding the permission in the facility's root organization (its staff)
or in a geographic organization above it (say, a district admin). Superusers
reach every facility.

One difference from Care: a facility with no geographic organization is
reached only through its own staff roles, never through a role held in some
other area.

Care 3.0 has no "Can View Resource Responses" (Care 3.1 added it), so there
a facility's feedback follows "Can Read on Facility" instead (view_feedback).
"""

from functools import cache

from care.emr.models.organization import FacilityOrganizationUser, OrganizationUser
from care.facility.models import Facility
from care.security.models import RolePermission
from django.db.models import Q

# Care's permission slugs, as text.
VIEW_RESPONSES = "can_view_resource_responses"  # reading a facility's questionnaire responses (Care 3.1+)
READ_FACILITY = "can_read_facility"  # reading the facility: for the feedback on Care 3.0, which lacks the above
MANAGE_FORMS = "can_update_facility"  # setting up a facility's forms is like editing the facility


@cache
def view_feedback() -> str:
    """The Care permission that opens a facility's feedback: VIEW_RESPONSES, or READ_FACILITY on Care 3.0."""
    from care.security.permissions.base import PermissionController

    # Asked when first needed, not at import: by then every plug has registered its permissions.
    return VIEW_RESPONSES if VIEW_RESPONSES in PermissionController.get_permissions() else READ_FACILITY


def facilities_with(user, *permissions: str):
    """
    The facilities where ``user`` holds any of ``permissions``, as a queryset,
    or None for every facility (superusers).
    """
    if user.is_superuser:
        return None
    roles = RolePermission.objects.filter(permission__slug__in=permissions).values("role_id")
    staff_of = FacilityOrganizationUser.objects.filter(
        user=user, role_id__in=roles, organization__org_type="root"
    ).values("organization__facility_id")
    areas = list(
        OrganizationUser.objects.filter(user=user, role_id__in=roles).values_list("organization_id", flat=True)
    )
    return Facility.objects.filter(Q(id__in=staff_of) | Q(geo_organization_cache__overlap=areas))


def facility_ids(user, *permissions: str):
    """The external ids of facilities_with(), for filtering this plugin's rows; None for every facility."""
    facilities = facilities_with(user, *permissions)
    return None if facilities is None else facilities.values_list("external_id", flat=True)


def reaches(user, facility, *permissions: str) -> bool:
    """Whether ``user`` holds any of ``permissions`` at ``facility`` (see facilities_with)."""
    facilities = facilities_with(user, *permissions)
    return facilities is None or facilities.filter(pk=facility.pk).exists()
