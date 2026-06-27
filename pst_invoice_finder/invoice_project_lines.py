from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


AMOUNT_RE = re.compile(r"(\d[\d\s\u00a0]*,\d{2})\s*$")
PROJECT_CODE_RE = re.compile(r"\b((?:25|26)\d{3})\b")
PROJECT_REFERENCE_RE = re.compile(
    r"\b(?P<code>(?:25|26)\d{3})\s*(?:[-–—]\s*(?P<name>[^,;|()\n\r]+))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProjectInvoiceLine:
    project_code: str
    project_name: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    net_amount: Decimal


def parse_decimal(value: str) -> Decimal:
    cleaned = (value or "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def split_paths(value: str | None) -> list[Path]:
    if not value:
        return []
    return [Path(part.strip()) for part in re.split(r";|\|", value) if part.strip()]


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def compact_line(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def candidate_project_code(codes: list[str]) -> str:
    if not codes:
        return ""
    return codes[0]


def project_name_from_parentheses(text: str, project_code: str) -> str:
    match = re.search(r"\((.*?)\)", text)
    content = match.group(1) if match else text
    content = compact_line(content)
    content = re.sub(rf"\b{re.escape(project_code)}\b", "", content)
    content = re.sub(r"^\d{5}\s*-\s*", "", content)
    content = re.split(r"/", content, maxsplit=1)[0]
    content = re.sub(r"\b[2-9]\d{4}\b", "", content)
    content = compact_line(content.strip(" -/"))
    return content or project_code


def parse_project_line(text: str) -> ProjectInvoiceLine | None:
    line = compact_line(text)
    if "AKT" not in line or "(" not in line:
        return None
    amount_match = AMOUNT_RE.search(line)
    if not amount_match:
        return None
    codes = PROJECT_CODE_RE.findall(line)
    project_code = candidate_project_code(codes)
    if not project_code:
        return None
    numbers = re.findall(r"(\d+(?:,\d{1,3})?)", line[amount_match.start() - 30 : amount_match.end()])
    quantity = Decimal("1")
    unit_price = Decimal("0")
    if len(numbers) >= 3:
        quantity = parse_decimal(numbers[-3])
        unit_price = parse_decimal(numbers[-2])
    net_amount = parse_decimal(amount_match.group(1))
    project_name = project_name_from_parentheses(line, project_code)
    description = compact_line(line[: amount_match.start()])
    description = re.sub(r"\s+\d+(?:,\d{1,3})?\s+\d[\d\s\u00a0]*(?:,\d{0,2})?\s*$", "", description).strip()
    return ProjectInvoiceLine(
        project_code=project_code,
        project_name=project_name,
        description=description or f"{project_code} {project_name}",
        quantity=quantity,
        unit_price=unit_price,
        net_amount=net_amount,
    )


def parse_project_reference_line(text: str) -> ProjectInvoiceLine | None:
    line = compact_line(text)
    if not re.search(r"objekti\s+viide|projekt|project", line, re.IGNORECASE):
        return None
    match = PROJECT_REFERENCE_RE.search(line)
    if not match:
        return None
    project_code = match.group("code")
    project_name = compact_line((match.group("name") or "").strip(" -"))
    project_name = re.sub(r"\s+Lk\s+\d+\s*/\s*\d+\s*$", "", project_name, flags=re.IGNORECASE)
    description = f"{project_code} {project_name}".strip()
    return ProjectInvoiceLine(
        project_code=project_code,
        project_name=project_name or project_code,
        description=description,
        quantity=Decimal("1"),
        unit_price=Decimal("0"),
        net_amount=Decimal("0"),
    )


def parse_project_lines_from_text(text: str) -> list[ProjectInvoiceLine]:
    rows: list[ProjectInvoiceLine] = []
    buffer = ""
    for raw_line in text.splitlines():
        line = compact_line(raw_line)
        if not line:
            continue
        if line.startswith("AKT"):
            if buffer:
                parsed = parse_project_line(buffer)
                if parsed:
                    rows.append(parsed)
            buffer = line
            if AMOUNT_RE.search(buffer):
                parsed = parse_project_line(buffer)
                if parsed:
                    rows.append(parsed)
                buffer = ""
            continue
        if buffer:
            buffer = compact_line(buffer + " " + line)
            if AMOUNT_RE.search(buffer):
                parsed = parse_project_line(buffer)
                if parsed:
                    rows.append(parsed)
                buffer = ""
    if buffer:
        parsed = parse_project_line(buffer)
        if parsed:
            rows.append(parsed)
    if not rows:
        seen: set[str] = set()
        for raw_line in text.splitlines():
            parsed = parse_project_reference_line(raw_line)
            if parsed and parsed.project_code not in seen:
                rows.append(parsed)
                seen.add(parsed.project_code)
    return rows


def parse_project_lines_from_attachments(attachment_paths: str | None) -> list[ProjectInvoiceLine]:
    rows: list[ProjectInvoiceLine] = []
    for path in split_paths(attachment_paths):
        if path.suffix.lower() != ".pdf" or not path.exists():
            continue
        rows.extend(parse_project_lines_from_text(extract_pdf_text(path)))
    return rows
