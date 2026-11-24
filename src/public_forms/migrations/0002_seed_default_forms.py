from django.db import migrations


class Migration(migrations.Migration):
    """
    Created the default OPD and inpatient forms, shared by every facility.
    Forms now belong to a facility (0005), so this does nothing on a new
    database: ``manage.py seed_feedback_forms <facility-id>`` gives a facility
    the default forms.
    """

    dependencies = [
        ("public_forms", "0001_initial"),
    ]

    operations = []
