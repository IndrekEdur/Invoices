from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.communications.models import CommunicationIntelligenceCandidate
from apps.communications.services import (
    CommunicationCandidateExtractionService,
    ExtractCommunicationCandidatesCommand,
)
from apps.core.models import Organization


class Command(BaseCommand):
    help = "Extract pending communication intelligence candidates from confirmed Project-linked e-mails."

    def add_arguments(self, parser):
        parser.add_argument("--organization", type=int, required=True)
        parser.add_argument("--message", action="append", type=int, dest="message_ids")
        parser.add_argument("--project", action="append", type=int, dest="project_ids")
        parser.add_argument("--date-from")
        parser.add_argument("--date-to")
        parser.add_argument("--candidate-type", action="append", dest="candidate_types")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force-reprocess", action="store_true")
        parser.add_argument("--provider", default="deterministic")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(id=options["organization"]).first()
        if not organization:
            raise CommandError("Organization not found.")
        if options["provider"] != "deterministic":
            raise CommandError("Only deterministic provider is available in this installation.")
        candidate_types = tuple(options.get("candidate_types") or ())
        self._validate_candidate_types(candidate_types)
        if not any((options.get("message_ids"), options.get("project_ids"), options.get("date_from"), options.get("limit"))):
            raise CommandError("Provide a bounded scope with --message, --project, --date-from or --limit.")

        try:
            result = CommunicationCandidateExtractionService.extract(
                ExtractCommunicationCandidatesCommand(
                    organization=organization,
                    email_message_ids=tuple(options.get("message_ids") or ()),
                    project_ids=tuple(options.get("project_ids") or ()),
                    date_from=self._parse_date(options.get("date_from")),
                    date_to=self._parse_date(options.get("date_to")),
                    candidate_types=candidate_types,
                    dry_run=options["dry_run"],
                    force_reprocess=options["force_reprocess"],
                    limit=options["limit"],
                    metadata={"source": "management_command", "limit": options["limit"]},
                )
            )
        except Exception as exc:
            if options["debug"]:
                raise
            raise CommandError(f"Candidate extraction failed: {exc.__class__.__name__}") from exc

        type_summary = ", ".join(f"{key}={value}" for key, value in sorted(result.candidate_count_by_type.items()))
        self.stdout.write(
            self.style.SUCCESS(
                "Communication candidate extraction completed: "
                f"evaluated={result.evaluated_messages}, "
                f"eligible={result.eligible_messages}, "
                f"created={result.created_count}, "
                f"updated={result.updated_count}, "
                f"unchanged={result.unchanged_count}, "
                f"skipped={result.skipped_count}, "
                f"duplicates={result.duplicate_count}, "
                f"failed={result.failed_count}, "
                f"dry_run={result.dry_run}, "
                f"types={type_summary or 'none'}"
            )
        )

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d").date()

    @staticmethod
    def _validate_candidate_types(candidate_types):
        valid = {choice for choice, _label in CommunicationIntelligenceCandidate.Type.choices}
        invalid = set(candidate_types) - valid
        if invalid:
            raise CommandError(f"Unsupported candidate type: {sorted(invalid)[0]}")
