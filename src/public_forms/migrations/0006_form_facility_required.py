from django.db import migrations, models


class Migration(migrations.Migration):
    """Every form belongs to a facility, with one form per code there (see 0005)."""

    dependencies = [
        ("public_forms", "0005_shared_forms_to_facilities"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="feedbackform",
            name="care_publicforms_shared_form_code",
        ),
        migrations.RemoveConstraint(
            model_name="feedbackform",
            name="care_publicforms_form_code_per_facility",
        ),
        migrations.AlterField(
            model_name="feedbackform",
            name="facility_external_id",
            field=models.UUIDField(
                help_text="The id of the facility that offers this form (the UUID in its Care URL).",
                verbose_name="facility id",
            ),
        ),
        migrations.AddConstraint(
            model_name="feedbackform",
            constraint=models.UniqueConstraint(
                fields=("facility_external_id", "code"), name="care_publicforms_form_code_per_facility"
            ),
        ),
    ]
