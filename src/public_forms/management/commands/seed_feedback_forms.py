import uuid

from django.core.management.base import BaseCommand, CommandError

from public_forms.models import FeedbackForm
from public_forms.seed import add_language_to_forms, create_default_forms, language_migrations


class Command(BaseCommand):
    help = (
        "Give facilities the default OPD and inpatient feedback forms they are missing, in every language that "
        "has a questionnaire migration (existing forms and text are left alone)."
    )

    def add_arguments(self, parser):
        parser.add_argument("facility_ids", nargs="+", metavar="facility-id", help="A facility's id (UUID).")

    def handle(self, *args, facility_ids, **options):
        from care.facility.models import Facility

        facilities = []
        for facility_id in facility_ids:
            facility = Facility.objects.filter(external_id=facility_id).first() if _is_uuid(facility_id) else None
            if facility is None:
                raise CommandError(f"No facility has the id {facility_id}.")
            facilities.append(facility)
        for facility in facilities:
            created = create_default_forms(FeedbackForm, facility.external_id)
            if created:
                self.stdout.write(self.style.SUCCESS(f"{facility.name}: created {', '.join(created)}"))
            else:
                self.stdout.write(f"{facility.name}: has every default form already.")
        for code, translations in language_migrations():
            add_language_to_forms(FeedbackForm, code, translations)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
