from .commands import EvaluateEmailProjectLinksCommand
from ..models import EmailProjectLink
from .project_linking import DeterministicEmailProjectLinkingService


class EmailProjectSuggestionService:
    """Compatibility wrapper for deterministic e-mail to Project suggestions.

    Existing import/sync processing calls this service. The implementation now delegates to the
    deterministic linker so there is one rules engine and one authoritative EmailProjectLink relation.
    """

    @staticmethod
    def suggest(command):
        result = DeterministicEmailProjectLinkingService.evaluate(
            EvaluateEmailProjectLinksCommand(
                organization=command.email_message.organization,
                email_message_ids=(command.email_message.id,),
                actor=command.actor,
                metadata=command.metadata,
            )
        )
        return [
            link
            for link in command.email_message.project_links.order_by("-confidence", "project__code", "id")
            if link.status == EmailProjectLink.Status.SUGGESTED
            and link.id
            and any(suggestion.project.id == link.project_id for suggestion in result.suggestions)
        ]
