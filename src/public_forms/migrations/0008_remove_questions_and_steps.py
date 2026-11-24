from django.db import migrations


class Migration(migrations.Migration):
    """The questions and step titles now live in the pages (0007), in a migration of its own."""

    dependencies = [
        ("public_forms", "0007_pages"),
    ]

    operations = [
        migrations.RemoveField(model_name="feedbackform", name="questions"),
        migrations.RemoveField(model_name="feedbackform", name="steps"),
    ]
