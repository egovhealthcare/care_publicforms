from django.db import migrations

DEFAULT_FORM_CODES = ("opd", "ipd")
DETAIL_KEYS = ("clinic", "ward", "date_of_admission", "age_group", "sex")


def require_details(apps, schema_editor):
    question_model = apps.get_model("patient_feedback", "FeedbackQuestion")
    question_model.objects.filter(
        form__facility__isnull=True, form__code__in=DEFAULT_FORM_CODES, key__in=DETAIL_KEYS
    ).update(required=True)


class Migration(migrations.Migration):
    """Make the default forms' detail questions (clinic / ward, date of admission, age, sex) required."""

    dependencies = [
        ("patient_feedback", "0002_seed_default_forms"),
    ]

    operations = [migrations.RunPython(require_details, migrations.RunPython.noop)]
