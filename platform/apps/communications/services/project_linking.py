import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.services import AuditService
from apps.projects.models import Project, ProjectParty

from ..models import EmailAttachment, EmailMessage, EmailProjectLink


RULE_VERSION = "deterministic-v1"


@dataclass(frozen=True)
class EmailProjectLinkSuggestion:
    email_message: object
    project: object
    source: str
    confidence_score: Decimal
    confidence_band: str
    is_primary_suggestion: bool
    evidence_summary: str
    evidence_metadata: dict = field(default_factory=dict)
    warnings: tuple = field(default_factory=tuple)
    rule_version: str = RULE_VERSION
    metadata: dict | None = None


@dataclass(frozen=True)
class EvaluateEmailProjectLinksResult:
    evaluated_messages: int
    matched_messages: int
    suggestion_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    skipped_count: int
    conflict_count: int
    failed_count: int
    suggestions: tuple = field(default_factory=tuple)
    warnings: tuple = field(default_factory=tuple)
    dry_run: bool = False
    metadata: dict | None = None


class DeterministicEmailProjectLinkingService:
    """Explainable, deterministic e-mail to Project linking using the existing EmailProjectLink relation.

    No new message, attachment or document relation is created here. EmailProjectLink remains the current
    authoritative message-to-Project relation; this service only evaluates deterministic evidence and persists
    suggested links when not running in dry-run mode.
    """

    @staticmethod
    def evaluate(command):
        metadata = dict(command.metadata or {})
        messages = DeterministicEmailProjectLinkingService._messages_for_command(command)
        projects = DeterministicEmailProjectLinkingService._projects_for_command(command)

        suggestions = []
        created_count = 0
        updated_count = 0
        unchanged_count = 0
        skipped_count = 0
        failed_count = 0
        conflict_count = 0
        matched_message_ids = set()
        warnings = []

        with transaction.atomic():
            for message in messages:
                try:
                    message_suggestions = DeterministicEmailProjectLinkingService.evaluate_message(
                        message,
                        command.organization,
                        projects=projects,
                        rule_sources=command.rule_sources,
                    )
                    if len({suggestion.project.id for suggestion in message_suggestions}) > 1:
                        conflict_count += 1
                        warnings.append(
                            {
                                "email_message_id": message.id,
                                "warning": "multiple_project_candidates",
                            }
                        )
                    if message_suggestions:
                        matched_message_ids.add(message.id)
                    suggestions.extend(message_suggestions)

                    if command.dry_run:
                        continue

                    for suggestion in message_suggestions:
                        outcome = DeterministicEmailProjectLinkingService._persist_suggestion(
                            suggestion,
                            actor=command.actor,
                            run_metadata=metadata,
                            force_reprocess=command.force_reprocess,
                        )
                        if outcome == "created":
                            created_count += 1
                        elif outcome == "updated":
                            updated_count += 1
                        elif outcome == "unchanged":
                            unchanged_count += 1
                        else:
                            skipped_count += 1
                except Exception:
                    failed_count += 1
                    raise

        return EvaluateEmailProjectLinksResult(
            evaluated_messages=len(messages),
            matched_messages=len(matched_message_ids),
            suggestion_count=len(suggestions),
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            skipped_count=skipped_count,
            conflict_count=conflict_count,
            failed_count=failed_count,
            suggestions=tuple(suggestions),
            warnings=tuple(warnings),
            dry_run=command.dry_run,
            metadata=metadata,
        )

    @staticmethod
    def evaluate_message(message, organization, *, projects=None, rule_sources=None):
        if message.organization_id != organization.id:
            raise ValueError("Email message belongs to a different organization.")

        allowed_sources = set(rule_sources or [])
        suggestions_by_project = {}
        projects = tuple(projects or Project.objects.filter(organization=organization).order_by("code", "id"))
        normalized_subject = DeterministicEmailProjectLinkingService._normalize_text(message.subject)
        normalized_body = DeterministicEmailProjectLinkingService._normalize_text(message.body_text)

        for project in projects:
            DeterministicEmailProjectLinkingService._collect_project_code_evidence(
                suggestions_by_project,
                message,
                project,
                normalized_subject,
                normalized_body,
                allowed_sources,
            )
            DeterministicEmailProjectLinkingService._collect_project_name_evidence(
                suggestions_by_project,
                message,
                project,
                normalized_subject,
                normalized_body,
                allowed_sources,
            )

        DeterministicEmailProjectLinkingService._collect_thread_evidence(
            suggestions_by_project,
            message,
            organization,
            allowed_sources,
        )
        DeterministicEmailProjectLinkingService._collect_attachment_evidence(
            suggestions_by_project,
            message,
            organization,
            projects,
            allowed_sources,
        )
        DeterministicEmailProjectLinkingService._boost_with_participant_evidence(
            suggestions_by_project,
            message,
            organization,
        )

        suggestions = [
            DeterministicEmailProjectLinkingService._build_suggestion(message, project, evidence_items)
            for project, evidence_items in suggestions_by_project.values()
        ]
        suggestions.sort(
            key=lambda suggestion: (
                -int(suggestion.confidence_score),
                DeterministicEmailProjectLinkingService._source_rank(suggestion.source),
                suggestion.project.code,
            )
        )
        return tuple(suggestions)

    @staticmethod
    def evidence_fingerprint(*, message_id, project_id, source, matched_value, matched_field, rule_version=RULE_VERSION):
        payload = {
            "message_id": message_id,
            "project_id": project_id,
            "source": source,
            "matched_value": DeterministicEmailProjectLinkingService._normalize_text(matched_value),
            "matched_field": matched_field,
            "rule_version": rule_version,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _messages_for_command(command):
        qs = EmailMessage.objects.filter(organization=command.organization).select_related("thread", "account")
        if command.email_message_ids:
            qs = qs.filter(id__in=command.email_message_ids)
        if command.account_ids:
            qs = qs.filter(account_id__in=command.account_ids)
        if command.mailbox:
            qs = qs.filter(metadata__mailbox=command.mailbox)
        if command.date_from:
            qs = qs.filter(Q(received_at__date__gte=command.date_from) | Q(sent_at__date__gte=command.date_from))
        if command.date_to:
            qs = qs.filter(Q(received_at__date__lte=command.date_to) | Q(sent_at__date__lte=command.date_to))
        return tuple(qs.order_by("received_at", "sent_at", "created_at", "id")[:500])

    @staticmethod
    def _projects_for_command(command):
        qs = Project.objects.filter(organization=command.organization).order_by("code", "id")
        if command.project_ids:
            qs = qs.filter(id__in=command.project_ids)
        return tuple(qs)

    @staticmethod
    def _collect_project_code_evidence(
        suggestions_by_project,
        message,
        project,
        normalized_subject,
        normalized_body,
        allowed_sources,
    ):
        if not project.code:
            return
        checks = (
            (
                EmailProjectLink.Source.EXACT_PROJECT_CODE_SUBJECT,
                "subject",
                normalized_subject,
                90,
                EmailProjectLink.ConfidenceBand.HIGH,
            ),
            (
                EmailProjectLink.Source.EXACT_PROJECT_CODE_BODY,
                "body_text",
                normalized_body,
                90,
                EmailProjectLink.ConfidenceBand.HIGH,
            ),
        )
        for source, field_name, haystack, confidence, band in checks:
            if allowed_sources and source not in allowed_sources:
                continue
            if DeterministicEmailProjectLinkingService._contains_project_code(haystack, project.code):
                DeterministicEmailProjectLinkingService._add_evidence(
                    suggestions_by_project,
                    message=message,
                    project=project,
                    source=source,
                    confidence=confidence,
                    confidence_band=band,
                    matched_field=field_name,
                    matched_value=project.code,
                    summary=f"Exact Project code {project.code} found in {field_name.replace('_', ' ')}.",
                )

    @staticmethod
    def _collect_project_name_evidence(
        suggestions_by_project,
        message,
        project,
        normalized_subject,
        normalized_body,
        allowed_sources,
    ):
        source = EmailProjectLink.Source.PROJECT_ALIAS
        if allowed_sources and source not in allowed_sources:
            return
        if not project.name:
            return
        normalized_name = DeterministicEmailProjectLinkingService._normalize_text(project.name)
        for field_name, haystack in (("subject", normalized_subject), ("body_text", normalized_body)):
            if normalized_name and normalized_name in haystack:
                DeterministicEmailProjectLinkingService._add_evidence(
                    suggestions_by_project,
                    message=message,
                    project=project,
                    source=source,
                    confidence=75,
                    confidence_band=EmailProjectLink.ConfidenceBand.MEDIUM,
                    matched_field=field_name,
                    matched_value=project.name,
                    summary=f"Exact Project name {project.name} found in {field_name.replace('_', ' ')}.",
                )

    @staticmethod
    def _collect_thread_evidence(suggestions_by_project, message, organization, allowed_sources):
        source = EmailProjectLink.Source.CONFIRMED_THREAD_LINK
        if allowed_sources and source not in allowed_sources:
            return
        if not message.thread_id:
            return
        confirmed_links = (
            EmailProjectLink.objects.filter(
                organization=organization,
                email_message__thread_id=message.thread_id,
                status=EmailProjectLink.Status.CONFIRMED,
            )
            .exclude(email_message=message)
            .select_related("project")
        )
        project_ids = {link.project_id for link in confirmed_links}
        if len(project_ids) != 1:
            return
        link = next(iter(confirmed_links))
        DeterministicEmailProjectLinkingService._add_evidence(
            suggestions_by_project,
            message=message,
            project=link.project,
            source=source,
            confidence=70,
            confidence_band=EmailProjectLink.ConfidenceBand.MEDIUM,
            matched_field="thread",
            matched_value=str(message.thread_id),
            summary=f"Inherited from confirmed thread Project {link.project.code}.",
            extra={"source_email_message_id": link.email_message_id, "thread_id": message.thread_id},
        )

    @staticmethod
    def _collect_attachment_evidence(suggestions_by_project, message, organization, projects, allowed_sources):
        source = EmailProjectLink.Source.ATTACHMENT_DOCUMENT_LINK
        attachments = tuple(
            EmailAttachment.objects.filter(organization=organization, email_message=message)
            .select_related("document")
            .order_by("id")
        )
        if not attachments:
            return
        if not allowed_sources or source in allowed_sources:
            for attachment in attachments:
                if attachment.document_id:
                    confirmed_links = (
                        EmailProjectLink.objects.filter(
                            organization=organization,
                            email_message__attachments__document=attachment.document,
                            status=EmailProjectLink.Status.CONFIRMED,
                        )
                        .exclude(email_message=message)
                        .select_related("project")
                        .distinct()
                    )
                    if confirmed_links.count() == 1:
                        link = confirmed_links.first()
                        DeterministicEmailProjectLinkingService._add_evidence(
                            suggestions_by_project,
                            message=message,
                            project=link.project,
                            source=source,
                            confidence=80,
                            confidence_band=EmailProjectLink.ConfidenceBand.HIGH,
                            matched_field="document",
                            matched_value=str(attachment.document_id),
                            summary=f"Attachment document is already linked to Project {link.project.code}.",
                            extra={
                                "attachment_id": attachment.id,
                                "document_id": attachment.document_id,
                                "source_email_message_id": link.email_message_id,
                            },
                        )

        for attachment in attachments:
            normalized_filename = DeterministicEmailProjectLinkingService._normalize_text(attachment.original_filename)
            for project in projects:
                if project.code and DeterministicEmailProjectLinkingService._contains_project_code(
                    normalized_filename,
                    project.code,
                ):
                    DeterministicEmailProjectLinkingService._add_evidence(
                        suggestions_by_project,
                        message=message,
                        project=project,
                        source=EmailProjectLink.Source.EXACT_PROJECT_CODE_SUBJECT,
                        confidence=90,
                        confidence_band=EmailProjectLink.ConfidenceBand.EXACT,
                        matched_field="attachment_filename",
                        matched_value=project.code,
                        summary=f"Exact Project code {project.code} found in attachment filename.",
                        extra={"attachment_id": attachment.id},
                    )

    @staticmethod
    def _boost_with_participant_evidence(suggestions_by_project, message, organization):
        participants = DeterministicEmailProjectLinkingService._message_participant_emails(message)
        if not participants:
            return
        project_ids = [project.id for project, _items in suggestions_by_project.values()]
        if not project_ids:
            return
        parties = ProjectParty.objects.filter(
            organization=organization,
            project_id__in=project_ids,
            is_active=True,
            email__in=participants,
        ).select_related("project")
        for party in parties:
            key = party.project_id
            if key not in suggestions_by_project:
                continue
            project, items = suggestions_by_project[key]
            items.append(
                {
                    "source": EmailProjectLink.Source.PARTICIPANT_PLUS_EVIDENCE,
                    "confidence": 5,
                    "confidence_band": EmailProjectLink.ConfidenceBand.LOW,
                    "matched_field": "participant",
                    "matched_value": party.email,
                    "summary": f"Participant {party.email} is linked to Project {project.code}.",
                    "fingerprint": DeterministicEmailProjectLinkingService.evidence_fingerprint(
                        message_id=message.id,
                        project_id=project.id,
                        source=EmailProjectLink.Source.PARTICIPANT_PLUS_EVIDENCE,
                        matched_value=party.email,
                        matched_field="participant",
                    ),
                    "metadata": {"project_party_id": party.id},
                }
            )

    @staticmethod
    def _add_evidence(
        suggestions_by_project,
        *,
        message,
        project,
        source,
        confidence,
        confidence_band,
        matched_field,
        matched_value,
        summary,
        extra=None,
    ):
        project_entry = suggestions_by_project.setdefault(project.id, (project, []))
        item = {
            "source": source,
            "confidence": confidence,
            "confidence_band": confidence_band,
            "matched_field": matched_field,
            "matched_value": matched_value,
            "summary": summary,
            "fingerprint": DeterministicEmailProjectLinkingService.evidence_fingerprint(
                message_id=message.id,
                project_id=project.id,
                source=source,
                matched_value=matched_value,
                matched_field=matched_field,
            ),
            "metadata": dict(extra or {}),
        }
        if source in {
            EmailProjectLink.Source.EXACT_PROJECT_CODE_SUBJECT,
            EmailProjectLink.Source.EXACT_PROJECT_CODE_BODY,
        }:
            item["matched_project_code"] = matched_value
        if source == EmailProjectLink.Source.PROJECT_ALIAS:
            item["matched_project_name"] = matched_value
        project_entry[1].append(item)

    @staticmethod
    def _build_suggestion(message, project, evidence_items):
        primary_item = sorted(
            evidence_items,
            key=lambda item: (
                DeterministicEmailProjectLinkingService._source_rank(item["source"]),
                -item["confidence"],
            ),
        )[0]
        confidence = min(100, max(item["confidence"] for item in evidence_items) + max(0, len(evidence_items) - 1) * 3)
        band = DeterministicEmailProjectLinkingService._confidence_band(confidence, primary_item["confidence_band"])
        evidence_metadata = {
            "matches": [
                DeterministicEmailProjectLinkingService._legacy_match_shape(item)
                for item in evidence_items
            ],
            "deterministic_matches": evidence_items,
            "fingerprints": sorted({item["fingerprint"] for item in evidence_items}),
            "rule_version": RULE_VERSION,
        }
        warnings = ()
        return EmailProjectLinkSuggestion(
            email_message=message,
            project=project,
            source=primary_item["source"],
            confidence_score=Decimal(confidence),
            confidence_band=band,
            is_primary_suggestion=primary_item["source"]
            in {
                EmailProjectLink.Source.EXACT_PROJECT_CODE_SUBJECT,
                EmailProjectLink.Source.EXACT_PROJECT_CODE_BODY,
                EmailProjectLink.Source.ATTACHMENT_DOCUMENT_LINK,
            },
            evidence_summary=primary_item["summary"],
            evidence_metadata=evidence_metadata,
            warnings=warnings,
            rule_version=RULE_VERSION,
            metadata={},
        )

    @staticmethod
    def _legacy_match_shape(item):
        legacy = {
            "matched_field": item["matched_field"],
            "confidence": item["confidence"],
        }
        if "matched_project_code" in item:
            legacy["matched_project_code"] = item["matched_project_code"]
        elif "matched_project_name" in item:
            legacy["matched_project_name"] = item["matched_project_name"]
        else:
            legacy["source"] = item["source"]
            legacy["matched_value"] = item["matched_value"]
        return legacy

    @staticmethod
    def _persist_suggestion(suggestion, *, actor, run_metadata, force_reprocess=False):
        link, created = EmailProjectLink.objects.get_or_create(
            email_message=suggestion.email_message,
            project=suggestion.project,
            defaults={
                "organization": suggestion.email_message.organization,
                "status": EmailProjectLink.Status.SUGGESTED,
            },
        )
        if link.organization_id != suggestion.email_message.organization_id:
            raise ValueError("EmailProjectLink organization mismatch.")

        if not created and link.status in {
            EmailProjectLink.Status.CONFIRMED,
            EmailProjectLink.Status.REJECTED,
            EmailProjectLink.Status.CORRECTED,
            EmailProjectLink.Status.SUPERSEDED,
        }:
            if link.status == EmailProjectLink.Status.CONFIRMED and force_reprocess:
                DeterministicEmailProjectLinkingService._enrich_link(link, suggestion)
                return "updated"
            return "skipped"

        fingerprint = DeterministicEmailProjectLinkingService._suggestion_fingerprint(suggestion)
        changed = created or any(
            (
                link.status != EmailProjectLink.Status.SUGGESTED,
                link.confidence != int(suggestion.confidence_score),
                link.confidence_band != suggestion.confidence_band,
                link.source != suggestion.source,
                link.evidence != suggestion.evidence_metadata,
                link.evidence_summary != suggestion.evidence_summary,
                link.evidence_fingerprint != fingerprint,
                link.rule_version != suggestion.rule_version,
            )
        )
        if changed:
            link.status = EmailProjectLink.Status.SUGGESTED
            link.confidence = int(suggestion.confidence_score)
            link.confidence_band = suggestion.confidence_band
            link.source = suggestion.source
            link.is_primary = False
            link.evidence = suggestion.evidence_metadata
            link.evidence_summary = suggestion.evidence_summary
            link.evidence_fingerprint = fingerprint
            link.rule_version = suggestion.rule_version
            link.last_evaluated_at = timezone.now()
            link.metadata = dict(run_metadata or {})
            link.save(
                update_fields=[
                    "status",
                    "confidence",
                    "confidence_band",
                    "source",
                    "is_primary",
                    "evidence",
                    "evidence_summary",
                    "evidence_fingerprint",
                    "rule_version",
                    "last_evaluated_at",
                    "metadata",
                    "updated_at",
                ]
            )
        else:
            link.last_evaluated_at = timezone.now()
            link.save(update_fields=["last_evaluated_at", "updated_at"])

        if created or changed:
            AuditService.record(
                event_type="email_project_link.suggested",
                message=f"Email project link suggested: {link}",
                organization=link.organization,
                actor=actor,
                object_type="EmailProjectLink",
                object_id=str(link.id),
                metadata={
                    "email_message_id": link.email_message_id,
                    "project_id": link.project_id,
                    "confidence": link.confidence,
                    "confidence_band": link.confidence_band,
                    "source": link.source,
                    "evidence_summary": link.evidence_summary,
                    "evidence_fingerprint": link.evidence_fingerprint,
                    "rule_version": link.rule_version,
                    "suggestion_metadata": dict(run_metadata or {}),
                    "created": created,
                },
            )
        return "created" if created else ("updated" if changed else "unchanged")

    @staticmethod
    def _enrich_link(link, suggestion):
        link.evidence = suggestion.evidence_metadata
        link.evidence_summary = suggestion.evidence_summary
        link.last_evaluated_at = timezone.now()
        link.rule_version = suggestion.rule_version
        link.save(update_fields=["evidence", "evidence_summary", "last_evaluated_at", "rule_version", "updated_at"])

    @staticmethod
    def _suggestion_fingerprint(suggestion):
        payload = {
            "message_id": suggestion.email_message.id,
            "project_id": suggestion.project.id,
            "source": suggestion.source,
            "fingerprints": suggestion.evidence_metadata.get("fingerprints", []),
            "rule_version": suggestion.rule_version,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _contains_project_code(value, code):
        if not value or not code:
            return False
        escaped = re.escape(DeterministicEmailProjectLinkingService._normalize_text(code))
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
        return bool(re.search(pattern, value, flags=re.IGNORECASE))

    @staticmethod
    def _normalize_text(value):
        normalized = unicodedata.normalize("NFKC", value or "")
        normalized = re.sub(r"<[^>]+>", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized.replace("\u00a0", " "))
        return normalized.strip().casefold()

    @staticmethod
    def _message_participant_emails(message):
        values = [message.sender_email]
        for field_name in ("recipients", "cc", "bcc"):
            for item in getattr(message, field_name) or []:
                if isinstance(item, dict):
                    values.append(item.get("email") or item.get("address") or "")
                else:
                    values.append(str(item))
        return {value.strip().casefold() for value in values if value}

    @staticmethod
    def _source_rank(source):
        order = {
            EmailProjectLink.Source.EXPLICIT_USER_LINK: 1,
            EmailProjectLink.Source.EXISTING_LEGACY_LINK: 1,
            EmailProjectLink.Source.EXACT_PROJECT_CODE_SUBJECT: 2,
            EmailProjectLink.Source.ATTACHMENT_DOCUMENT_LINK: 3,
            EmailProjectLink.Source.EXACT_PROJECT_CODE_BODY: 4,
            EmailProjectLink.Source.CONFIRMED_THREAD_LINK: 5,
            EmailProjectLink.Source.PROJECT_ALIAS: 6,
            EmailProjectLink.Source.PARTICIPANT_PLUS_EVIDENCE: 7,
            EmailProjectLink.Source.IMPORTED_BACKFILL: 8,
        }
        return order.get(source, 99)

    @staticmethod
    def _confidence_band(score, fallback):
        if score >= 95:
            return EmailProjectLink.ConfidenceBand.EXACT
        if score >= 80:
            return EmailProjectLink.ConfidenceBand.HIGH
        if score >= 60:
            return EmailProjectLink.ConfidenceBand.MEDIUM
        return fallback or EmailProjectLink.ConfidenceBand.LOW


class CommunicationProjectLinkReviewService:
    """Audited human lifecycle actions for the current EmailProjectLink implementation."""

    @staticmethod
    def confirm(command):
        link = command.link
        metadata = dict(command.metadata or {})
        CommunicationProjectLinkReviewService._validate_link(link)

        with transaction.atomic():
            if command.make_primary:
                EmailProjectLink.objects.filter(
                    organization=link.organization,
                    email_message=link.email_message,
                    status=EmailProjectLink.Status.CONFIRMED,
                    is_primary=True,
                ).exclude(id=link.id).update(is_primary=False, status=EmailProjectLink.Status.SUPERSEDED)

            link.status = EmailProjectLink.Status.CONFIRMED
            link.is_primary = bool(command.make_primary)
            link.source = link.source or EmailProjectLink.Source.EXPLICIT_USER_LINK
            link.confidence_band = link.confidence_band or EmailProjectLink.ConfidenceBand.EXACT
            link.confirmed_by = command.actor
            link.confirmed_at = timezone.now()
            link.metadata = {**dict(link.metadata or {}), **metadata}
            link.save(
                update_fields=[
                    "status",
                    "is_primary",
                    "source",
                    "confidence_band",
                    "confirmed_by",
                    "confirmed_at",
                    "metadata",
                    "updated_at",
                ]
            )

            AuditService.record(
                event_type="email_project_link.confirmed",
                message=f"Email project link confirmed: {link}",
                organization=link.organization,
                actor=command.actor,
                object_type="EmailProjectLink",
                object_id=str(link.id),
                metadata={
                    "email_message_id": link.email_message_id,
                    "project_id": link.project_id,
                    "make_primary": command.make_primary,
                    "reason": command.reason,
                    "decision_metadata": metadata,
                },
            )
            return link

    @staticmethod
    def reject(command):
        link = command.link
        metadata = dict(command.metadata or {})
        CommunicationProjectLinkReviewService._validate_link(link)

        with transaction.atomic():
            link_metadata = dict(link.metadata or {})
            if command.reason:
                link_metadata["rejection_reason"] = command.reason
            link_metadata.update(metadata)
            link.status = EmailProjectLink.Status.REJECTED
            link.is_primary = False
            link.metadata = link_metadata
            link.save(update_fields=["status", "is_primary", "metadata", "updated_at"])

            AuditService.record(
                event_type="email_project_link.rejected",
                message=f"Email project link rejected: {link}",
                organization=link.organization,
                actor=command.actor,
                object_type="EmailProjectLink",
                object_id=str(link.id),
                metadata={
                    "email_message_id": link.email_message_id,
                    "project_id": link.project_id,
                    "reason": command.reason,
                    "decision_metadata": metadata,
                },
            )
            return link

    @staticmethod
    def correct(command):
        message = command.email_message
        project = command.project
        if message.organization_id != project.organization_id:
            raise ValueError("Email message and Project belong to different organizations.")
        metadata = dict(command.metadata or {})

        with transaction.atomic():
            if command.make_primary:
                EmailProjectLink.objects.filter(
                    organization=message.organization,
                    email_message=message,
                    status=EmailProjectLink.Status.CONFIRMED,
                    is_primary=True,
                ).update(is_primary=False, status=EmailProjectLink.Status.SUPERSEDED)

            link, _created = EmailProjectLink.objects.get_or_create(
                organization=message.organization,
                email_message=message,
                project=project,
                defaults={
                    "status": EmailProjectLink.Status.CONFIRMED,
                    "confidence": 100,
                    "confidence_band": EmailProjectLink.ConfidenceBand.EXACT,
                    "source": EmailProjectLink.Source.EXPLICIT_USER_LINK,
                    "is_primary": command.make_primary,
                    "evidence_summary": f"User explicitly linked e-mail to Project {project.code}.",
                    "evidence": {"reason": command.reason},
                    "metadata": metadata,
                },
            )
            if not _created:
                link.status = EmailProjectLink.Status.CONFIRMED
                link.confidence = max(link.confidence, 100)
                link.confidence_band = EmailProjectLink.ConfidenceBand.EXACT
                link.source = EmailProjectLink.Source.EXPLICIT_USER_LINK
                link.is_primary = bool(command.make_primary)
                link.evidence_summary = f"User explicitly linked e-mail to Project {project.code}."
                link.metadata = {**dict(link.metadata or {}), **metadata}
            link.confirmed_by = command.actor
            link.confirmed_at = timezone.now()
            link.save()

            AuditService.record(
                event_type="email_project_link.corrected",
                message=f"Email project link corrected: {message} -> {project.code}",
                organization=message.organization,
                actor=command.actor,
                object_type="EmailProjectLink",
                object_id=str(link.id),
                metadata={
                    "email_message_id": message.id,
                    "project_id": project.id,
                    "make_primary": command.make_primary,
                    "reason": command.reason,
                    "decision_metadata": metadata,
                },
            )
            return link

    @staticmethod
    def _validate_link(link):
        if link.organization_id != link.email_message.organization_id:
            raise ValueError("EmailProjectLink organization does not match EmailMessage organization.")
        if link.organization_id != link.project.organization_id:
            raise ValueError("EmailProjectLink organization does not match Project organization.")
