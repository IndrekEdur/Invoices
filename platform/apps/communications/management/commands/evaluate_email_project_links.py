from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.communications.services import (
    DeterministicEmailProjectLinkingService,
    EvaluateEmailProjectLinksCommand,
)
from apps.core.models import Organization


class Command(BaseCommand):
    help = "Evaluate deterministic e-mail to Project link suggestions for a bounded scope."

    def add_arguments(self, parser):
        parser.add_argument("--organization", type=int, required=True)
        parser.add_argument("--message", action="append", type=int, dest="message_ids")
        parser.add_argument("--project", action="append", type=int, dest="project_ids")
        parser.add_argument("--account", action="append", type=int, dest="account_ids")
        parser.add_argument("--date-from")
        parser.add_argument("--date-to")
        parser.add_argument("--source", action="append", dest="sources")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force-reprocess", action="store_true")
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(id=options["organization"]).first()
        if not organization:
            raise CommandError("Organization not found.")

        if not any((options.get("message_ids"), options.get("account_ids"), options.get("date_from"), options.get("project_ids"))):
            raise CommandError("Provide a bounded scope with --message, --account, --project or --date-from.")

        try:
            result = DeterministicEmailProjectLinkingService.evaluate(
                EvaluateEmailProjectLinksCommand(
                    organization=organization,
                    email_message_ids=tuple(options.get("message_ids") or ()),
                    account_ids=tuple(options.get("account_ids") or ()),
                    date_from=self._parse_date(options.get("date_from")),
                    date_to=self._parse_date(options.get("date_to")),
                    project_ids=tuple(options.get("project_ids") or ()),
                    rule_sources=tuple(options.get("sources") or ()),
                    dry_run=options["dry_run"],
                    force_reprocess=options["force_reprocess"],
                    metadata={"source": "management_command"},
                )
            )
        except Exception as exc:
            if options["debug"]:
                raise
            raise CommandError(f"Email project link evaluation failed: {exc.__class__.__name__}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Email project link evaluation completed: "
                f"evaluated={result.evaluated_messages}, "
                f"matched={result.matched_messages}, "
                f"suggestions={result.suggestion_count}, "
                f"created={result.created_count}, "
                f"updated={result.updated_count}, "
                f"unchanged={result.unchanged_count}, "
                f"skipped={result.skipped_count}, "
                f"conflicts={result.conflict_count}, "
                f"dry_run={result.dry_run}"
            )
        )

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d").date()
