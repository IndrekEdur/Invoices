from __future__ import annotations

from pathlib import Path


def extract_pdf_preview(path: Path, max_chars: int = 2000) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    try:
        reader = PdfReader(str(path))
        chunks: list[str] = []
        for page in reader.pages[:3]:
            text = page.extract_text() or ""
            if text:
                chunks.append(text)
            if sum(len(chunk) for chunk in chunks) >= max_chars:
                break
        preview = "\n".join(chunks).strip()
        return preview[:max_chars] if preview else None
    except Exception:
        return None
