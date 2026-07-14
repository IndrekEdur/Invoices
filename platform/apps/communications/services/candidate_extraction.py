import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from ..models import CommunicationIntelligenceCandidate, EmailMessage, EmailProjectLink


EXTRACTOR_VERSION = "communication-candidates-v1"
RULE_VERSION = "deterministic-rules-v1"
MAX_EXCERPT_LENGTH = 240


@dataclass(frozen=True)
class CommunicationExtractionContext:
    message_id: int
    project_id: int
    project_code: str
    project_name: str
    subject: str
    clean_body: str
    sender: str
    recipients: tuple = field(default_factory=tuple)
    message_date: object = None
    thread_context: tuple = field(default_factory=tuple)
    language: str = "unknown"
    metadata: dict | None = None


@dataclass(frozen=True)
class ExtractedCommunicationCandidate:
    candidate_type: str
    title: str
    description: str
    confidence_score: Decimal | None
    confidence_band: str
    evidence_excerpt: str
    evidence_span: tuple | None = None
    suggested_responsible_email: str = ""
    suggested_due_date: object = None
    suggested_priority: str = ""
    extraction_method: str = CommunicationIntelligenceCandidate.ExtractionMethod.DETERMINISTIC_RULE
    warnings: tuple = field(default_factory=tuple)
    metadata: dict | None = None


@dataclass(frozen=True)
class ExtractCommunicationCandidatesResult:
    evaluated_messages: int
    eligible_messages: int
    created_count: int
    updated_count: int
    unchanged_count: int
    skipped_count: int
    duplicate_count: int
    failed_count: int
    candidate_count_by_type: dict
    candidates: tuple = field(default_factory=tuple)
    warnings: tuple = field(default_factory=tuple)
    dry_run: bool = False
    metadata: dict | None = None


class CommunicationIntelligenceProvider:
    """Provider boundary for candidate extraction.

    Providers receive immutable DTO context and return immutable DTO candidates. They must not write to
    the database or receive ORM objects directly.
    """

    provider_name = "base"
    model_name = ""
    model_version = ""
    prompt_version = ""

    def extract_candidates(self, context):
        raise NotImplementedError


class DeterministicCommunicationIntelligenceProvider(CommunicationIntelligenceProvider):
    provider_name = "deterministic"
    model_name = "rules"
    model_version = RULE_VERSION

    def extract_candidates(self, context):
        text = "\n".join(part for part in (context.subject, context.clean_body) if part).strip()
        if not text:
            return tuple()

        candidates = []
        for sentence, start, end in self._sentences(text):
            lowered = sentence.casefold()
            candidates.extend(self._question_candidates(sentence, lowered, start, end))
            candidates.extend(self._task_candidates(sentence, lowered, start, end, context))
            candidates.extend(self._commitment_candidates(sentence, lowered, start, end, context))
            candidates.extend(self._decision_candidates(sentence, lowered, start, end))
            candidates.extend(self._risk_candidates(sentence, lowered, start, end))
            candidates.extend(self._blocker_candidates(sentence, lowered, start, end))
            candidates.extend(self._deadline_candidates(sentence, lowered, start, end, context))
            candidates.extend(self._resolution_candidates(sentence, lowered, start, end))

        if not candidates and self._information_only(text):
            candidates.append(
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.INFORMATION_ONLY,
                    "Information update",
                    text[:MAX_EXCERPT_LENGTH],
                    text[:MAX_EXCERPT_LENGTH],
                    (0, min(len(text), MAX_EXCERPT_LENGTH)),
                    Decimal("40.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.LOW,
                    warnings=("information_only",),
                )
            )
        return tuple(candidates)

    def _question_candidates(self, sentence, lowered, start, end):
        patterns = ("?", "kas ", "palun kinnitage", "please confirm", "can you", "could you")
        if any(pattern in lowered for pattern in patterns):
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.QUESTION,
                    self._title("Question", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("80.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.HIGH,
                ),
            )
        return tuple()

    def _task_candidates(self, sentence, lowered, start, end, context):
        patterns = ("palun saada", "palun saatke", "please provide", "please send", "vajame", "please prepare")
        if any(pattern in lowered for pattern in patterns):
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.TASK_REQUEST,
                    self._title("Task request", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("75.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.HIGH,
                    suggested_due_date=self._parse_due_date(sentence, context.message_date),
                ),
            )
        return tuple()

    def _commitment_candidates(self, sentence, lowered, start, end, context):
        patterns = ("saadan", "teen ", "we will provide", "i will send", "we will send", "i will provide")
        if any(pattern in lowered for pattern in patterns):
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.COMMITMENT,
                    self._title("Commitment", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("75.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.HIGH,
                    suggested_responsible_email=context.sender,
                    suggested_due_date=self._parse_due_date(sentence, context.message_date),
                ),
            )
        return tuple()

    def _decision_candidates(self, sentence, lowered, start, end):
        patterns = ("kinnitatud", "approved", "otsustasime", "we agreed")
        if any(pattern in lowered for pattern in patterns):
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.DECISION,
                    self._title("Decision", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("70.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.MEDIUM,
                ),
            )
        return tuple()

    def _risk_candidates(self, sentence, lowered, start, end):
        patterns = ("risk", "oht", "may delay", "delay risk", "might not")
        if any(pattern in lowered for pattern in patterns):
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.RISK,
                    self._title("Risk", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("65.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.MEDIUM,
                ),
            )
        return tuple()

    def _blocker_candidates(self, sentence, lowered, start, end):
        patterns = ("blocked", "blocker", "takistus", "ei saa jätkata", "cannot continue")
        if any(pattern in lowered for pattern in patterns):
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.BLOCKER,
                    self._title("Blocker", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("70.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.MEDIUM,
                ),
            )
        return tuple()

    def _deadline_candidates(self, sentence, lowered, start, end, context):
        due_date = self._parse_due_date(sentence, context.message_date)
        if due_date:
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.DEADLINE,
                    self._title("Deadline", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("65.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.MEDIUM,
                    suggested_due_date=due_date,
                ),
            )
        return tuple()

    def _resolution_candidates(self, sentence, lowered, start, end):
        patterns = ("resolved", "done", "completed", "vastatud", "lahendatud")
        if any(pattern in lowered for pattern in patterns):
            return (
                self._candidate(
                    CommunicationIntelligenceCandidate.Type.RESOLUTION_EVIDENCE,
                    self._title("Resolution evidence", sentence),
                    sentence,
                    sentence,
                    (start, end),
                    Decimal("60.00"),
                    CommunicationIntelligenceCandidate.ConfidenceBand.MEDIUM,
                ),
            )
        return tuple()

    @staticmethod
    def _candidate(
        candidate_type,
        title,
        description,
        excerpt,
        span,
        confidence_score,
        confidence_band,
        *,
        suggested_responsible_email="",
        suggested_due_date=None,
        warnings=(),
    ):
        bounded_excerpt = excerpt[:MAX_EXCERPT_LENGTH]
        return ExtractedCommunicationCandidate(
            candidate_type=candidate_type,
            title=title[:255],
            description=description[:500],
            confidence_score=confidence_score,
            confidence_band=confidence_band,
            evidence_excerpt=bounded_excerpt,
            evidence_span=span,
            suggested_responsible_email=suggested_responsible_email or "",
            suggested_due_date=suggested_due_date,
            extraction_method=CommunicationIntelligenceCandidate.ExtractionMethod.DETERMINISTIC_RULE,
            warnings=tuple(warnings),
            metadata={"rule_version": RULE_VERSION},
        )

    @staticmethod
    def _sentences(text):
        current = []
        start = 0
        for index, char in enumerate(text):
            current.append(char)
            if char in ".?!\n":
                sentence = "".join(current).strip()
                if sentence:
                    yield sentence, start, index + 1
                current = []
                start = index + 1
        sentence = "".join(current).strip()
        if sentence:
            yield sentence, start, len(text)

    @staticmethod
    def _title(prefix, sentence):
        return f"{prefix}: {sentence[:80].strip()}"

    @staticmethod
    def _information_only(text):
        lowered = text.casefold()
        return any(pattern in lowered for pattern in ("for your information", "fyi", "infoks", "teadmiseks"))

    @staticmethod
    def _parse_due_date(sentence, message_date):
        lowered = sentence.casefold()
        iso_match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", lowered)
        if iso_match:
            from datetime import date

            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        local_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", lowered)
        if local_match:
            from datetime import date

            return date(int(local_match.group(3)), int(local_match.group(2)), int(local_match.group(1)))
        if not message_date:
            return None
        base_date = message_date.date() if hasattr(message_date, "date") else message_date
        if "tomorrow" in lowered or "homme" in lowered:
            return base_date + timedelta(days=1)
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
        }
        for name, target in weekdays.items():
            if f"by {name}" in lowered:
                days = (target - base_date.weekday()) % 7
                return base_date + timedelta(days=days or 7)
        return None


class CommunicationCandidateExtractionService:
    @staticmethod
    def extract(command):
        metadata = dict(command.metadata or {})
        provider = command.provider or DeterministicCommunicationIntelligenceProvider()
        candidate_types = set(command.candidate_types or [])
        CommunicationCandidateExtractionService._validate_candidate_types(candidate_types)
        messages = CommunicationCandidateExtractionService._messages(command)

        created_count = 0
        updated_count = 0
        unchanged_count = 0
        skipped_count = 0
        duplicate_count = 0
        failed_count = 0
        eligible_messages = 0
        all_candidates = []
        warnings = []

        with transaction.atomic():
            for message in messages:
                links = CommunicationCandidateExtractionService._confirmed_links(message, command)
                if not links:
                    skipped_count += 1
                    continue
                if not (message.subject or message.body_text):
                    skipped_count += 1
                    continue
                eligible_messages += 1
                for link in links:
                    context = CommunicationCandidateExtractionService._context(message, link, command.include_thread_context)
                    content_fingerprint = CommunicationCandidateExtractionService.content_fingerprint(context)
                    if not command.force_reprocess and CommunicationIntelligenceCandidate.objects.filter(
                        organization=command.organization,
                        email_message=message,
                        project=link.project,
                        content_fingerprint=content_fingerprint,
                        extractor_version=EXTRACTOR_VERSION,
                    ).exists():
                        skipped_count += 1
                        continue
                    try:
                        extracted = provider.extract_candidates(context)
                    except Exception as exc:
                        failed_count += 1
                        warnings.append({"message_id": message.id, "error": exc.__class__.__name__})
                        continue
                    seen = set()
                    for candidate in extracted:
                        if candidate_types and candidate.candidate_type not in candidate_types:
                            continue
                        CommunicationCandidateExtractionService._validate_candidate(candidate)
                        evidence_fingerprint = CommunicationCandidateExtractionService.evidence_fingerprint(
                            context,
                            candidate,
                            provider,
                        )
                        if evidence_fingerprint in seen:
                            duplicate_count += 1
                            continue
                        seen.add(evidence_fingerprint)
                        all_candidates.append(candidate)
                        if command.dry_run:
                            continue
                        outcome = CommunicationCandidateExtractionService._persist_candidate(
                            command=command,
                            context=context,
                            candidate=candidate,
                            link=link,
                            provider=provider,
                            content_fingerprint=content_fingerprint,
                            evidence_fingerprint=evidence_fingerprint,
                            metadata=metadata,
                        )
                        if outcome == "created":
                            created_count += 1
                        elif outcome == "updated":
                            updated_count += 1
                        else:
                            unchanged_count += 1

        counts_by_type = {}
        for candidate in all_candidates:
            counts_by_type[candidate.candidate_type] = counts_by_type.get(candidate.candidate_type, 0) + 1

        return ExtractCommunicationCandidatesResult(
            evaluated_messages=len(messages),
            eligible_messages=eligible_messages,
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            skipped_count=skipped_count,
            duplicate_count=duplicate_count,
            failed_count=failed_count,
            candidate_count_by_type=counts_by_type,
            candidates=tuple(all_candidates),
            warnings=tuple(warnings),
            dry_run=command.dry_run,
            metadata=metadata,
        )

    @staticmethod
    def content_fingerprint(context):
        payload = {
            "message_id": context.message_id,
            "project_id": context.project_id,
            "subject": CommunicationCandidateExtractionService._normalize(context.subject),
            "body": CommunicationCandidateExtractionService._normalize(context.clean_body),
            "extractor_version": EXTRACTOR_VERSION,
        }
        return CommunicationCandidateExtractionService._sha256(payload)

    @staticmethod
    def evidence_fingerprint(context, candidate, provider):
        payload = {
            "message_id": context.message_id,
            "project_id": context.project_id,
            "candidate_type": candidate.candidate_type,
            "evidence_excerpt": CommunicationCandidateExtractionService._normalize(candidate.evidence_excerpt),
            "evidence_span": candidate.evidence_span,
            "extractor_version": EXTRACTOR_VERSION,
            "provider": provider.provider_name,
            "model": provider.model_name,
            "model_version": provider.model_version,
            "prompt_version": provider.prompt_version,
        }
        return CommunicationCandidateExtractionService._sha256(payload)

    @staticmethod
    def _persist_candidate(
        *,
        command,
        context,
        candidate,
        link,
        provider,
        content_fingerprint,
        evidence_fingerprint,
        metadata,
    ):
        existing = CommunicationIntelligenceCandidate.objects.filter(
            organization=command.organization,
            email_message_id=context.message_id,
            project_id=context.project_id,
            candidate_type=candidate.candidate_type,
            evidence_fingerprint=evidence_fingerprint,
        ).first()
        if existing and existing.status != CommunicationIntelligenceCandidate.Status.PENDING_REVIEW:
            return "unchanged"

        defaults = CommunicationCandidateExtractionService._candidate_fields(
            context,
            candidate,
            link,
            provider,
            content_fingerprint,
            evidence_fingerprint,
            metadata,
        )
        if not existing:
            CommunicationIntelligenceCandidate.objects.create(**defaults)
            return "created"
        changed = False
        for field_name, value in defaults.items():
            if field_name in {"organization", "project", "email_message", "email_thread"}:
                continue
            if getattr(existing, field_name) != value:
                setattr(existing, field_name, value)
                changed = True
        if changed:
            existing.save()
            return "updated"
        return "unchanged"

    @staticmethod
    def _candidate_fields(context, candidate, link, provider, content_fingerprint, evidence_fingerprint, metadata):
        return {
            "organization": link.organization,
            "project": link.project,
            "email_message": link.email_message,
            "email_thread": link.email_message.thread,
            "candidate_type": candidate.candidate_type,
            "status": CommunicationIntelligenceCandidate.Status.PENDING_REVIEW,
            "title": candidate.title,
            "description": candidate.description,
            "confidence_score": candidate.confidence_score,
            "confidence_band": candidate.confidence_band,
            "extraction_method": candidate.extraction_method,
            "suggested_responsible_email": candidate.suggested_responsible_email,
            "suggested_due_date": candidate.suggested_due_date,
            "suggested_priority": candidate.suggested_priority,
            "source_evidence_summary": candidate.evidence_excerpt,
            "evidence_excerpt": candidate.evidence_excerpt[:MAX_EXCERPT_LENGTH],
            "evidence_fingerprint": evidence_fingerprint,
            "content_fingerprint": content_fingerprint,
            "extractor_version": EXTRACTOR_VERSION,
            "model_provider": provider.provider_name if provider.provider_name != "deterministic" else "",
            "model_name": provider.model_name if provider.provider_name != "deterministic" else "",
            "model_version": provider.model_version,
            "prompt_version": provider.prompt_version,
            "rule_version": RULE_VERSION,
            "metadata": {
                **dict(metadata or {}),
                "warnings": list(candidate.warnings),
                "evidence_span": candidate.evidence_span,
                "project_link_id": link.id,
                "candidate_metadata": dict(candidate.metadata or {}),
            },
        }

    @staticmethod
    def _messages(command):
        qs = EmailMessage.objects.filter(organization=command.organization).select_related("thread", "account")
        if command.email_message_ids:
            qs = qs.filter(id__in=command.email_message_ids)
        if command.date_from:
            qs = qs.filter(Q(received_at__date__gte=command.date_from) | Q(sent_at__date__gte=command.date_from))
        if command.date_to:
            qs = qs.filter(Q(received_at__date__lte=command.date_to) | Q(sent_at__date__lte=command.date_to))
        return tuple(qs.order_by("received_at", "sent_at", "created_at", "id")[: max(1, command.limit or 100)])

    @staticmethod
    def _confirmed_links(message, command):
        qs = EmailProjectLink.objects.filter(
            organization=command.organization,
            email_message=message,
            status=EmailProjectLink.Status.CONFIRMED,
        ).select_related("project")
        if command.project_ids:
            qs = qs.filter(project_id__in=command.project_ids)
        return tuple(qs.order_by("-is_primary", "project__code", "id"))

    @staticmethod
    def _context(message, link, include_thread_context):
        thread_context = ()
        if include_thread_context and message.thread_id:
            thread_context = tuple(
                EmailMessage.objects.filter(organization=message.organization, thread=message.thread)
                .exclude(id=message.id)
                .order_by("-received_at", "-sent_at", "-created_at")[:3]
                .values_list("subject", flat=True)
            )
        return CommunicationExtractionContext(
            message_id=message.id,
            project_id=link.project_id,
            project_code=link.project.code,
            project_name=link.project.name,
            subject=message.subject or "",
            clean_body=CommunicationCandidateExtractionService._clean_body(message.body_text or ""),
            sender=message.sender_email or "",
            recipients=tuple(message.recipients or ()),
            message_date=message.received_at or message.sent_at or message.created_at,
            thread_context=thread_context,
            language=CommunicationCandidateExtractionService._language(message.subject, message.body_text),
            metadata={"email_project_link_id": link.id},
        )

    @staticmethod
    def _clean_body(value):
        lines = []
        for line in (value or "").splitlines():
            stripped = line.strip()
            lowered = stripped.casefold()
            if not stripped:
                continue
            if stripped.startswith(">") or lowered.startswith(("from:", "sent:", "subject:", "-----original message")):
                continue
            if lowered in {"best regards", "regards", "lugupidamisega"}:
                break
            lines.append(stripped)
        return "\n".join(lines)[:4000]

    @staticmethod
    def _language(subject, body):
        text = f"{subject} {body}".casefold()
        if any(token in text for token in (" kas ", "palun", "kinnitage", "homme", "kuupäev")):
            return "et"
        if any(token in text for token in ("please", "confirm", "tomorrow", "approved")):
            return "en"
        return "unknown"

    @staticmethod
    def _validate_candidate_types(candidate_types):
        valid = {choice for choice, _label in CommunicationIntelligenceCandidate.Type.choices}
        invalid = set(candidate_types) - valid
        if invalid:
            raise ValueError(f"Unsupported candidate type: {sorted(invalid)[0]}")

    @staticmethod
    def _validate_candidate(candidate):
        valid_types = {choice for choice, _label in CommunicationIntelligenceCandidate.Type.choices}
        if candidate.candidate_type not in valid_types:
            raise ValueError(f"Unsupported candidate type: {candidate.candidate_type}")
        if len(candidate.evidence_excerpt) > MAX_EXCERPT_LENGTH:
            raise ValueError("Candidate evidence excerpt is too long.")

    @staticmethod
    def _normalize(value):
        return re.sub(r"\s+", " ", (value or "").strip().casefold())

    @staticmethod
    def _sha256(payload):
        serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
