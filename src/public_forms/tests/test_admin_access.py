from care.emr.models import FacilityOrganization
from care.utils.tests.base import CareAPITestBase
from django.contrib.auth.models import Permission
from django.test import RequestFactory, override_settings
from django.urls import reverse

from public_forms.access import MANAGE_FORMS, VIEW_FEEDBACK
from public_forms.admin_site import site
from public_forms.models import FeedbackForm, FeedbackSubmission
from public_forms.tests import PLAIN_STATIC_STORAGES, TEST_PLUGIN_CONFIGS
from public_forms.tests.test_api import make_submission

SUBMISSIONS = reverse("public_forms_admin:public_forms_feedbacksubmission_changelist")
FORMS = reverse("public_forms_admin:public_forms_feedbackform_changelist")


@override_settings(STORAGES=PLAIN_STATIC_STORAGES, PLUGIN_CONFIGS=TEST_PLUGIN_CONFIGS)
class AdminFacilityAccessTests(CareAPITestBase):
    """The admin's permissions say what a user may do; Care's roles say at which facilities."""

    def setUp(self):
        super().setUp()
        creator = self.create_user()
        self.district = self.create_organization(org_type="govt", name="Mysuru district")
        self.mysuru = self.create_facility(user=creator, name="Mysuru hospital", geo_organization=self.district)
        self.hassan = self.create_facility(user=creator, name="Hassan hospital", geo_organization=None)
        make_submission(self.mysuru, "OPD-MYS", "opd", {"overall_satisfaction": 4})
        make_submission(self.mysuru, "IPD-MYS", "ipd", {"diet": 3})
        make_submission(self.hassan, "OPD-HAS", "opd", {"overall_satisfaction": 2})
        self.viewer = self.create_role_with_permissions([VIEW_FEEDBACK])
        self.manager = self.create_role_with_permissions([MANAGE_FORMS])

    def admin_user(self, *codenames):
        """A staff user with this app's permissions (no Care role yet), signed in."""
        user = self.create_user(is_active=True, is_staff=True, is_superuser=False)
        user.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="public_forms", codename__in=codenames)
        )
        self.client.force_login(user)
        return user

    def staff_role(self, user, facility, role):
        root = FacilityOrganization.objects.get(facility=facility, org_type="root")
        self.attach_role_facility_organization_user(root, user, role)

    def opd(self, facility):
        return FeedbackForm.objects.get(facility_external_id=facility.external_id, code="opd")

    def change_url(self, obj):
        return reverse(f"public_forms_admin:public_forms_{obj._meta.model_name}_change", args=[obj.pk])

    def export(self):
        response = self.client.post(
            SUBMISSIONS,
            {"action": "export_csv", "_selected_action": FeedbackSubmission.objects.values_list("pk", flat=True)},
        )
        return b"".join(response.streaming_content).decode()

    def test_facility_staff_see_only_their_facility(self):
        user = self.admin_user("view_feedbacksubmission")
        self.staff_role(user, self.mysuru, self.viewer)
        page = self.client.get(SUBMISSIONS)
        self.assertContains(page, "OPD-MYS")
        self.assertNotContains(page, "OPD-HAS")
        # The form filter lists only the forms of what is shown.
        mysuru_ipd = FeedbackForm.objects.get(facility_external_id=self.mysuru.external_id, code="ipd")
        self.assertContains(page, f"form__id__exact={self.opd(self.mysuru).pk}")
        self.assertContains(page, f"form__id__exact={mysuru_ipd.pk}")
        self.assertNotContains(page, f"form__id__exact={self.opd(self.hassan).pk}")
        # Another facility's submission can't be opened by its address, nor exported.
        other = FeedbackSubmission.objects.get(reference_number="OPD-HAS")
        response = self.client.get(self.change_url(other))
        self.assertRedirects(response, reverse("public_forms_admin:index"), fetch_redirect_response=False)
        export = self.export()
        self.assertIn("OPD-MYS", export)
        self.assertNotIn("OPD-HAS", export)

    def test_area_admins_see_the_facilities_in_their_area(self):
        user = self.admin_user("view_feedbacksubmission")
        self.attach_role_organization_user(self.district, user, self.viewer)
        page = self.client.get(SUBMISSIONS)
        self.assertContains(page, "OPD-MYS")
        self.assertNotContains(page, "OPD-HAS")  # no area: only its own staff see it

    def test_a_role_without_the_permission_shows_nothing(self):
        user = self.admin_user("view_feedbacksubmission")
        self.staff_role(user, self.mysuru, self.manager)  # sets up forms, doesn't read feedback
        page = self.client.get(SUBMISSIONS)
        self.assertNotContains(page, "OPD-MYS")
        self.assertNotContains(page, "OPD-HAS")

    def test_this_apps_permissions_alone_reach_no_facility(self):
        self.admin_user("view_feedbacksubmission", "view_feedbackform", "change_feedbackform", "add_feedbackform")
        page = self.client.get(SUBMISSIONS)
        self.assertNotContains(page, "OPD-MYS")
        self.assertNotContains(page, "OPD-HAS")
        self.assertNotContains(self.client.get(FORMS), "hospital")
        self.assertEqual(self.export().count("\n"), 1)  # the header only
        # Nowhere to set up a form.
        add = reverse("public_forms_admin:public_forms_feedbackform_add")
        self.assertEqual(self.client.get(add).status_code, 403)

    def test_superusers_see_every_facility(self):
        self.client.force_login(self.create_super_user(is_staff=True))
        page = self.client.get(SUBMISSIONS)
        self.assertContains(page, "OPD-MYS")
        self.assertContains(page, "OPD-HAS")
        self.assertEqual(self.client.get(self.change_url(self.opd(self.hassan))).status_code, 200)

    def test_forms_are_set_up_only_where_the_user_manages_the_facility(self):
        user = self.admin_user("view_feedbackform", "change_feedbackform", "add_feedbackform")
        self.staff_role(user, self.mysuru, self.manager)
        self.staff_role(user, self.hassan, self.viewer)
        forms = self.client.get(FORMS)
        self.assertContains(forms, "Mysuru hospital")
        self.assertContains(forms, "Hassan hospital")  # its feedback is theirs to read
        # Their facility's form can be changed; the other one is read-only.
        self.assertContains(self.client.get(self.change_url(self.opd(self.mysuru))), 'name="_save"')
        hassan_opd = self.client.get(self.change_url(self.opd(self.hassan)))
        self.assertEqual(hassan_opd.status_code, 200)
        self.assertNotContains(hassan_opd, 'name="_save"')
        self.assertEqual(self.client.post(self.change_url(self.opd(self.hassan)), {}).status_code, 403)

        # A new form, or a form moved, only to a facility they manage.
        request = RequestFactory().get(FORMS)
        request.user = user
        form_class = site._registry[FeedbackForm].get_form(request)
        base = {"code": "eye_opd", "patient_type": "op", "title__en": "Eye OPD", "order": 0}
        elsewhere = form_class(data={**base, "facility_external_id": str(self.hassan.external_id)})
        self.assertEqual(elsewhere.errors["facility_external_id"], ["You can't set up forms for this facility."])
        own = form_class(data={**base, "facility_external_id": str(self.mysuru.external_id)})
        self.assertTrue(own.is_valid(), own.errors)
