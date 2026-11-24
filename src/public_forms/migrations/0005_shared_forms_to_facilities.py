from django.db import migrations

# A form without a facility used to be shared by every facility. Now every
# form belongs to one facility. Each facility that has feedback on a shared
# form gets its own copy of it (or keeps its own form with that code, if it
# already had one), and that feedback moves to it. The shared forms are then
# removed, so a facility with no feedback on one needs a form of its own:
# ``manage.py seed_feedback_forms <facility-id>`` or the admin. 0006 then
# makes the facility required (a separate migration, so this one's changes
# are committed before the table is altered).
COPIED_FIELDS = ("code", "patient_type", "title", "description", "questions", "steps", "is_active", "order")


def give_shared_forms_to_facilities(form_model, submission_model):
    for shared in form_model.objects.filter(facility_external_id__isnull=True):
        submissions = submission_model.objects.filter(form=shared)
        facility_ids = submissions.order_by().values_list("facility_external_id", flat=True).distinct()
        for facility_id in list(facility_ids):
            own = form_model.objects.filter(facility_external_id=facility_id, code=shared.code).first()
            if own is None:
                own = form_model.objects.create(
                    facility_external_id=facility_id, **{name: getattr(shared, name) for name in COPIED_FIELDS}
                )
            submissions.filter(facility_external_id=facility_id).update(form=own)
        shared.delete()


def forwards(apps, schema_editor):
    give_shared_forms_to_facilities(
        apps.get_model("public_forms", "FeedbackForm"), apps.get_model("public_forms", "FeedbackSubmission")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("public_forms", "0004_numbered_steps"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
