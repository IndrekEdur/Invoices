from django.core.management.base import BaseCommand, CommandError

from apps.communications.models import EmailAccount
from apps.communications.services import EmailSyncService, SyncEmailAccountCommand


class Command(BaseCommand):
    help = "Sync one e-mail account through the configured provider connector."

    def add_arguments(self, parser):
        parser.add_argument("email_account_id", type=int)
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--process", action="store_true")

    def handle(self, *args, **options):
        email_account_id = options["email_account_id"]
        limit = options["limit"]
        process_imported = options["process"]

        try:
            email_account = EmailAccount.objects.get(id=email_account_id)
        except EmailAccount.DoesNotExist as exc:
            raise CommandError(f"EmailAccount not found: {email_account_id}") from exc

        try:
            result = EmailSyncService.sync(
                SyncEmailAccountCommand(
                    email_account=email_account,
                    limit=limit,
                    process_imported=process_imported,
                )
            )
        except Exception as exc:
            raise CommandError(f"Email sync failed: {exc}") from exc

        self.stdout.write(f"account: {email_account.email_address}")
        self.stdout.write(f"fetched_count: {result['fetched_count']}")
        self.stdout.write(f"imported_count: {result['imported_count']}")
        self.stdout.write(f"processed_count: {result['processed_count']}")
        self.stdout.write(f"synced: {result['synced']}")
