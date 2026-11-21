from django.db import migrations


def seed(apps, schema_editor):
    from public_forms.seed import create_default_forms

    create_default_forms(apps.get_model("public_forms", "FeedbackForm"))


class Migration(migrations.Migration):
    """Create the default OPD and inpatient forms (NQAS format); they can be edited in the admin afterwards."""

    dependencies = [
        ("public_forms", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
