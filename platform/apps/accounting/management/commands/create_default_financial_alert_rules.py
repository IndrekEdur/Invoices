from django.core.management.base import BaseCommand, CommandError

from apps.accounting.services import FinancialAlertRuleService
from apps.core.models import Organization


class Command(BaseCommand):
    help = "Create the default financial alert rules for one Organization."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, type=int)

    def handle(self, *args, **options):
        organization_id = options["organization"]
        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist as exc:
            raise CommandError(f"Organization not found: {organization_id}") from exc

        rules = FinancialAlertRuleService.create_default_rules(organization)
        self.stdout.write(f"organization_id: {organization.id}")
        self.stdout.write(f"rule_count: {len(rules)}")
        self.stdout.write("created_or_existing: true")
