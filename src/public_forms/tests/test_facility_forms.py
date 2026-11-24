import importlib
import io
from unittest import mock

from care.utils.tests.base import CareAPITestBase
from django.core.management import CommandError, call_command
from django.db import connection

from public_forms.models import FeedbackForm, FeedbackSubmission
from public_forms.tests import default_forms

shared_forms_migration = importlib.import_module("public_forms.migrations.0005_shared_forms_to_facilities")


class FacilityFormsTests(CareAPITestBase):
    def submission(self, facility, form, reference):
        return FeedbackSubmission.objects.create(
            reference_number=reference, facility_external_id=facility.external_id, form=form, language="en"
        )

    def test_shared_forms_become_the_facilities_own(self):
        # Before 0006 a form could have no facility: it was shared by every
        # facility. Undone with the test's transaction.
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE care_publicforms_form ALTER COLUMN facility_external_id DROP NOT NULL")
        user = self.create_user()
        mysuru, hassan, unused = (self.create_facility(user=user, name=name) for name in ("Mysuru", "Hassan", "Unused"))
        shared_opd = FeedbackForm.objects.create(
            code="opd",
            patient_type="op",
            title={"en": "OPD", "kn": "ಒಪಿಡಿ"},
            description={"en": "About your visit"},
            pages=[{"questions": [{"key": "care", "type": "rating", "text": {"en": "Care"}}]}],
            order=3,
        )
        FeedbackForm.objects.create(code="ipd", patient_type="ip", title={"en": "IPD"})  # no feedback anywhere
        hassan_opd = FeedbackForm.objects.create(
            facility_external_id=hassan.external_id, code="opd", patient_type="op", title={"en": "Hassan OPD"}
        )
        for facility, form, reference in (
            (mysuru, shared_opd, "OPD-1"),
            (mysuru, shared_opd, "OPD-2"),
            (hassan, shared_opd, "OPD-3"),
            (hassan, hassan_opd, "OPD-4"),
        ):
            self.submission(facility, form, reference)

        # 0005 copies the fields of its time; today's model has the pages instead (0007).
        copied = tuple(
            "pages" if name == "questions" else name for name in shared_forms_migration.COPIED_FIELDS if name != "steps"
        )
        with mock.patch.object(shared_forms_migration, "COPIED_FIELDS", copied):
            shared_forms_migration.give_shared_forms_to_facilities(FeedbackForm, FeedbackSubmission)

        mysuru_opd = FeedbackForm.objects.get(facility_external_id=mysuru.external_id)
        self.assertEqual([getattr(mysuru_opd, name) for name in copied], [getattr(shared_opd, name) for name in copied])
        forms = dict(FeedbackSubmission.objects.values_list("reference_number", "form"))
        self.assertEqual(
            forms, {"OPD-1": mysuru_opd.pk, "OPD-2": mysuru_opd.pk, "OPD-3": hassan_opd.pk, "OPD-4": hassan_opd.pk}
        )
        # Hassan keeps its own form; the shared forms are gone, and a facility
        # without feedback on them gets no copy.
        self.assertEqual(
            sorted(FeedbackForm.objects.values_list("facility_external_id", "code")),
            sorted([(mysuru.external_id, "opd"), (hassan.external_id, "opd")]),
        )
        self.assertFalse(FeedbackForm.objects.filter(facility_external_id=unused.external_id).exists())

    def test_seed_command_gives_facilities_the_default_forms(self):
        user = self.create_user()
        first, second = self.create_facility(user=user, name="First"), self.create_facility(user=user, name="Second")
        FeedbackForm.objects.create(
            facility_external_id=second.external_id, code="ipd", patient_type="ip", title={"en": "Ours"}
        )
        out = io.StringIO()
        call_command("seed_feedback_forms", str(first.external_id), str(second.external_id), stdout=out)
        self.assertIn("First: created opd, ipd", out.getvalue())
        self.assertIn("Second: created opd", out.getvalue())
        self.assertEqual(default_forms(second)["ipd"].title, {"en": "Ours"})  # an existing form is left alone
        again = io.StringIO()
        call_command("seed_feedback_forms", str(first.external_id), stdout=again)
        self.assertIn("First: has every default form already.", again.getvalue())
        for wrong in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
            with self.assertRaisesMessage(CommandError, f"No facility has the id {wrong}."):
                call_command("seed_feedback_forms", wrong, stdout=io.StringIO())
