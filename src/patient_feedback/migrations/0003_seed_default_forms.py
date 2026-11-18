from django.db import migrations


def seed(apps, schema_editor):
    from patient_feedback.seed import create_default_forms

    create_default_forms(apps.get_model("patient_feedback", "FeedbackForm"), apps.get_model("patient_feedback", "FeedbackQuestion"))


class Migration(migrations.Migration):
    """Create the default OPD and inpatient forms (NQAS format); they can be edited in the admin afterwards."""

    dependencies = [
        ("patient_feedback", "0002_configurable_forms"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
