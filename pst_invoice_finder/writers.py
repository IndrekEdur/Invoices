from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import InvoiceCandidate


CSV_FIELDS = [
    "score",
    "sent_at",
    "folder",
    "sender_name",
    "sender_email",
    "subject",
    "reasons",
    "attachment_names",
    "saved_attachments",
]


def write_csv(path: Path, candidates: list[InvoiceCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate.as_dict())


def write_json(path: Path, candidates: list[InvoiceCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [candidate.as_dict() for candidate in candidates]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
