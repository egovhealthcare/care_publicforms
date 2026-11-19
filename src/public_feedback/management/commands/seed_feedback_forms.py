from django.core.management.base import BaseCommand

from public_feedback.models import FeedbackForm
from public_feedback.seed import create_default_forms


class Command(BaseCommand):
    help = "Create the default OPD and inpatient feedback forms if they are missing (existing forms are left alone)."

    def handle(self, *args, **options):
        created = create_default_forms(FeedbackForm)
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created forms: {', '.join(created)}"))
        else:
            self.stdout.write("All default forms already exist.")
