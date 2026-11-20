from django.core.management.base import BaseCommand

from care_publicforms.models import FeedbackForm
from care_publicforms.seed import add_language_to_forms, create_default_forms, language_migrations


class Command(BaseCommand):
    help = (
        "Create the default OPD and inpatient feedback forms if they are missing, in every language that has "
        "a questionnaire migration (existing text is left alone)."
    )

    def handle(self, *args, **options):
        created = create_default_forms(FeedbackForm)
        for code, translations in language_migrations():
            add_language_to_forms(FeedbackForm, code, translations)
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created forms: {', '.join(created)}"))
        else:
            self.stdout.write("All default forms already exist.")
