from __future__ import annotations

import re
from pathlib import Path

from .models import EmailInfo, InvoiceCandidate


INVOICE_WORDS = (
    "arve",
    "invoice",
    "faktuur",
    "bill",
    "rechnung",
    "ostuarve",
    "müügiarve",
    "muugiarve",
    "käibemaks",
    "kaibemaks",
    "km",
)

RECEIPT_WORDS = (
    "receipt",
    "kviitung",
    "tsekk",
    "tšekk",
    "payment",
    "makse",
)

NEGATIVE_WORDS = (
    "newsletter",
    "uudiskiri",
    "reklaam",
    "campaign",
)

INVOICE_EXTENSIONS = {".pdf", ".xml", ".asice", ".bdoc", ".ddoc", ".xlsx", ".xls", ".csv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def score_email(email: EmailInfo) -> tuple[int, list[str]]:
    haystack = " ".join(
        [
            email.subject or "",
            email.sender_name or "",
            email.sender_email or "",
            email.body_preview or "",
            " ".join(a.filename for a in email.attachments),
            " ".join(a.text_preview or "" for a in email.attachments),
        ]
    ).lower()

    score = 0
    reasons: list[str] = []

    invoice_hits = [word for word in INVOICE_WORDS if word in haystack]
    if invoice_hits:
        score += min(45, 18 + len(invoice_hits) * 7)
        reasons.append("invoice keywords: " + ", ".join(sorted(set(invoice_hits))))

    receipt_hits = [word for word in RECEIPT_WORDS if word in haystack]
    if receipt_hits:
        score += min(25, 10 + len(receipt_hits) * 5)
        reasons.append("receipt/payment keywords: " + ", ".join(sorted(set(receipt_hits))))

    invoice_attachments = [
        a.filename
        for a in email.attachments
        if Path(a.filename).suffix.lower() in INVOICE_EXTENSIONS
    ]
    if invoice_attachments:
        score += 25
        reasons.append("invoice-like attachments: " + ", ".join(invoice_attachments[:5]))

    named_image_attachments = [
        a.filename
        for a in email.attachments
        if Path(a.filename).suffix.lower() in IMAGE_EXTENSIONS
        and any(word in a.filename.lower() for word in ("arve", "invoice", "receipt", "tsekk"))
    ]
    if named_image_attachments:
        score += 15
        reasons.append("named image attachments: " + ", ".join(named_image_attachments[:5]))

    if re.search(r"\b(arve|invoice|nr|no\.?)\s*[:#-]?\s*[a-z0-9][a-z0-9./-]{2,}", haystack):
        score += 15
        reasons.append("possible invoice number")

    if re.search(r"\b\d+[,.]\d{2}\s*(eur|€)\b", haystack):
        score += 10
        reasons.append("possible euro amount")

    negative_hits = [word for word in NEGATIVE_WORDS if word in haystack]
    if negative_hits:
        score -= 25
        reasons.append("negative keywords: " + ", ".join(sorted(set(negative_hits))))

    return max(0, min(100, score)), reasons


def make_candidate(email: EmailInfo, min_score: int) -> InvoiceCandidate | None:
    score, reasons = score_email(email)
    if score < min_score:
        return None

    return InvoiceCandidate(
        folder=email.folder,
        subject=email.subject,
        sender_name=email.sender_name,
        sender_email=email.sender_email,
        sent_at=email.sent_at.isoformat() if email.sent_at else None,
        score=score,
        reasons=reasons,
        attachment_names=[a.filename for a in email.attachments],
        saved_attachments=[a.saved_path for a in email.attachments if a.saved_path],
    )
