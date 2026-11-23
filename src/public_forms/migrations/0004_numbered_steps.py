from django.db import migrations, models

# Each question's "step" is now a number: the screen that asks it, in order.
# This writes it into the questions of the forms that exist, right after
# "type", where they were already asked (details 1, ratings 2, open 3), so
# nothing moves on screen. A step given by name becomes its number; a number
# is kept. Forms also get optional step titles (empty: default headings).
DEFAULT_STEPS = {"choice": 1, "date": 1, "rating": 2, "text": 3}
STEP_NAMES = {"details": 1, "ratings": 2, "open": 3}


def numbered(questions):
    if not isinstance(questions, list):
        return questions
    out = []
    for question in questions:
        default = DEFAULT_STEPS.get(question.get("type")) if isinstance(question, dict) else None
        if default:
            if "step" not in question:
                ordered = {}
                for name, value in question.items():
                    ordered[name] = value
                    if name == "type":
                        ordered["step"] = default
                question = ordered
            elif question["step"] in STEP_NAMES:
                question = {**question, "step": STEP_NAMES[question["step"]]}
        out.append(question)
    return out


def number_steps(form_model):
    for form in form_model.objects.all():
        questions = numbered(form.questions)
        if questions != form.questions:
            form.questions = questions
            form.save(update_fields=["questions"])


def forwards(apps, schema_editor):
    number_steps(apps.get_model("public_forms", "FeedbackForm"))


class Migration(migrations.Migration):
    dependencies = [
        ("public_forms", "0003_hyphens_in_range_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="feedbackform",
            name="steps",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    'Optional heading for a step, by its number, per language: {"1": {"title": {"en": "About you"}, '
                    '"lead": {"en": "…"}}}. Steps without one get a default heading. Rating steps take none: each '
                    "card shows its question."
                ),
                verbose_name="step titles",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
