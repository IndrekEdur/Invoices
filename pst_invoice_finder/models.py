from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class AttachmentInfo:
    filename: str
    size: int | None = None
    saved_path: str | None = None
    text_preview: str | None = None


@dataclass
class EmailInfo:
    folder: str
    subject: str
    sender_name: str | None
    sender_email: str | None
    sent_at: datetime | None
    body_preview: str
    attachments: list[AttachmentInfo] = field(default_factory=list)


@dataclass
class InvoiceCandidate:
    folder: str
    subject: str
    sender_name: str | None
    sender_email: str | None
    sent_at: str | None
    score: int
    reasons: list[str]
    attachment_names: list[str]
    saved_attachments: list[str]

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["reasons"] = "; ".join(self.reasons)
        row["attachment_names"] = "; ".join(self.attachment_names)
        row["saved_attachments"] = "; ".join(self.saved_attachments)
        return row


def safe_path_name(value: str, fallback: str = "attachment") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in value).strip()
    return cleaned or fallback


def make_month_key(dt: datetime | None) -> str:
    if not dt:
        return "unknown-month"
    return f"{dt:%Y-%m}"


def make_output_path(base_dir: Path, sent_at: datetime | None, folder: str, filename: str) -> Path:
    month = make_month_key(sent_at)
    folder_part = safe_path_name(folder.replace("\\", "_").replace("/", "_"), "folder")
    return base_dir / month / folder_part / safe_path_name(filename)
