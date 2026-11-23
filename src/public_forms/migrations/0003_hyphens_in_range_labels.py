from django.db import migrations

# The default forms wrote number ranges with an en dash. They now use a plain
# hyphen, as in "10-30 mins" and "18-30". This updates forms created before
# the change, in every language. Only these exact default labels are changed,
# so a label reworded in the admin keeps its wording.
EN_DASH = "\u2013"
OLD_LABELS = [
    f"10{EN_DASH}30 mins",
    f"5{EN_DASH}10 mins",
    f"18{EN_DASH}30",
    f"31{EN_DASH}45",
    f"46{EN_DASH}60",
    f"10{EN_DASH}30 ನಿಮಿಷ",
    f"5{EN_DASH}10 ನಿಮಿಷ",
]
NEW_LABELS = {old: old.replace(EN_DASH, "-") for old in OLD_LABELS}


def with_hyphens(value):
    """``value`` (a form's title, description or questions) with the old labels replaced."""
    if isinstance(value, dict):
        return {key: with_hyphens(item) for key, item in value.items()}
    if isinstance(value, list):
        return [with_hyphens(item) for item in value]
    if isinstance(value, str):
        return NEW_LABELS.get(value, value)
    return value


def use_hyphens(form_model):
    for form in form_model.objects.all():
        changed = []
        for field in ("title", "description", "questions"):
            new = with_hyphens(getattr(form, field))
            if new != getattr(form, field):
                setattr(form, field, new)
                changed.append(field)
        if changed:
            form.save(update_fields=changed)


def forwards(apps, schema_editor):
    use_hyphens(apps.get_model("public_forms", "FeedbackForm"))


class Migration(migrations.Migration):
    dependencies = [
        ("public_forms", "0002_seed_default_forms"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
