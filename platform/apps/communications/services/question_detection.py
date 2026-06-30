from django.db import transaction

from apps.core.services import AuditService

from ..models import EmailQuestion


class EmailQuestionDetectionService:
    """Rules-based question and action detection for e-mail messages."""

    ESTONIAN_KEYWORDS = ("kas", "millal", "miks", "kuidas", "palun", "kinnitage", "saatke")
    ENGLISH_KEYWORDS = ("can you", "could you", "please", "confirm", "when", "why", "how")

    @staticmethod
    def detect(command):
        email_message = command.email_message
        metadata = dict(command.metadata or {})
        evidence_items = EmailQuestionDetectionService._collect_evidence(email_message)

        if not evidence_items:
            return []

        confidence = max(item["confidence"] for item in evidence_items)
        question_text = EmailQuestionDetectionService._question_text(email_message)

        with transaction.atomic():
            question = EmailQuestion.objects.create(
                organization=email_message.organization,
                email_message=email_message,
                question_text=question_text,
                detection_method=EmailQuestion.DetectionMethod.RULE_BASED,
                confidence=confidence,
                evidence={"matches": evidence_items},
                metadata=metadata,
            )

            AuditService.record(
                event_type="email_question.detected",
                message=f"Email question detected: {email_message}",
                organization=email_message.organization,
                actor=command.actor,
                object_type="EmailQuestion",
                object_id=str(question.id),
                metadata={
                    "email_message_id": email_message.id,
                    "confidence": confidence,
                    "evidence": {"matches": evidence_items},
                    "detection_metadata": metadata,
                },
            )

            return [question]

    @staticmethod
    def _collect_evidence(email_message):
        evidence = []
        for field_name, value in (
            ("subject", email_message.subject or ""),
            ("body_text", email_message.body_text or ""),
        ):
            if "?" in value:
                evidence.append(
                    {
                        "matched_field": field_name,
                        "rule": "question_mark",
                        "confidence": 70,
                    }
                )

            lower_value = value.casefold()
            for keyword in EmailQuestionDetectionService.ESTONIAN_KEYWORDS:
                if keyword in lower_value:
                    evidence.append(
                        {
                            "matched_field": field_name,
                            "rule": "estonian_keyword",
                            "keyword": keyword,
                            "confidence": 60,
                        }
                    )
            for keyword in EmailQuestionDetectionService.ENGLISH_KEYWORDS:
                if keyword in lower_value:
                    evidence.append(
                        {
                            "matched_field": field_name,
                            "rule": "english_keyword",
                            "keyword": keyword,
                            "confidence": 60,
                        }
                    )

        return evidence

    @staticmethod
    def _question_text(email_message):
        if email_message.body_text:
            return email_message.body_text

        return email_message.subject or ""
