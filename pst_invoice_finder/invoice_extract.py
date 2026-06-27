from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .invoice_db import connect


DATE_RE = r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})"
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9 ]{10,34}\b", re.IGNORECASE)
IBAN_LENGTHS = {
    "EE": 20,
    "SE": 24,
    "LV": 21,
    "LT": 20,
    "FI": 18,
    "DE": 22,
    "NO": 15,
    "DK": 18,
    "PL": 28,
    "NL": 18,
}
REG_RE = re.compile(
    r"\b(?:registrikood|reg\.?\s*kood|reg\.?\s*nr\.?|reg\.?\s*no\.?|registreerimisnr\.?|registreerimis\s*nr\.?)\s*:?\s*([A-Z0-9-]{6,15})\b",
    re.IGNORECASE,
)
KMKR_RE = re.compile(r"\b(?:kmkr|kmkr\s*nr|käibemaksukohustuslase\s*nr|kaibemaksukohustuslase\s*nr|vat\s*no\.?)\s*:?\s*([A-Z]{2}[A-Z0-9]{8,14})\b", re.IGNORECASE)


@dataclass
class ExtractedInvoiceFields:
    issuer_name: str = ""
    invoice_number: str = ""
    amount_total: str = ""
    vat_amount: str = ""
    payment_details: str = ""
    due_date: str = ""
    invoice_date: str = ""
    issuer_reg_code: str = ""
    issuer_vat_no: str = ""
    currency: str = "EUR"
    extraction_status: str = "not_started"
    extraction_note: str = ""
    source_files: list[str] = field(default_factory=list)

    def as_update_fields(self) -> dict[str, str]:
        return {
            "issuer_name": self.issuer_name,
            "invoice_number": self.invoice_number,
            "amount_total": self.amount_total,
            "vat_amount": self.vat_amount,
            "payment_details": self.payment_details,
            "due_date": self.due_date,
            "invoice_date": self.invoice_date,
            "issuer_reg_code": self.issuer_reg_code,
            "issuer_vat_no": self.issuer_vat_no,
            "currency": self.currency,
            "extraction_status": self.extraction_status,
            "extraction_note": self.extraction_note,
        }


def normalize_amount(value: str) -> str:
    value = value.strip().replace(" ", "").replace("\u00a0", "")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", ".")
    return value


def normalize_iban(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def valid_iban_length(value: str) -> bool:
    iban = normalize_iban(value)
    expected = IBAN_LENGTHS.get(iban[:2])
    if expected:
        return len(iban) == expected
    return 15 <= len(iban) <= 34


def parse_amount(value: str) -> float | None:
    try:
        return float(normalize_amount(value))
    except (TypeError, ValueError):
        return None


def format_amount(value: float) -> str:
    return f"{value:.2f}"


def normalize_date(value: str) -> str:
    value = value.strip().replace(".", "-").replace("/", "-")
    parts = value.split("-")
    if len(parts) != 3:
        return value
    if len(parts[0]) == 4:
        year, month, day = parts
    else:
        day, month, year = parts
        if len(year) == 2:
            year = "20" + year
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def extract_pdf_text(path: Path) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            chunks = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text:
                    chunks.append(text)
            if chunks:
                return "\n".join(chunks)
    except Exception:
        pass

    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(str(path))
        chunks = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                chunks.append(text)
        return "\n".join(chunks)
    except Exception:
        return ""


def extract_xml_text_and_fields(path: Path) -> tuple[str, ExtractedInvoiceFields]:
    fields = ExtractedInvoiceFields(extraction_status="partial", source_files=[str(path)])
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return "", fields

    values: list[str] = []
    tagged: dict[str, list[str]] = {}
    for element in root.iter():
        tag = element.tag.split("}", 1)[-1].lower()
        text = (element.text or "").strip()
        if not text:
            continue
        values.append(text)
        tagged.setdefault(tag, []).append(text)

    def first(*tags: str) -> str:
        for tag in tags:
            values_for_tag = tagged.get(tag.lower(), [])
            if values_for_tag:
                return values_for_tag[0]
        return ""

    fields.amount_total = normalize_amount(first("TotalSum", "TotalAmount", "PayableAmount", "InvoiceSum"))
    fields.vat_amount = normalize_amount(first("VATSum", "TaxAmount", "TotalVATSum"))
    fields.invoice_date = normalize_date(first("InvoiceDate", "IssueDate", "Date"))
    fields.due_date = normalize_date(first("DueDate", "PaymentDate"))
    fields.issuer_reg_code = first("RegNumber", "RegistrationNumber", "SellerRegNumber")
    fields.issuer_vat_no = first("VATRegNumber", "SellerVATRegNumber", "TaxRegistrationNumber")
    iban = first("IBAN", "AccountNumber", "SellerPartyIBAN")
    if iban:
        fields.payment_details = iban.replace(" ", "")

    return "\n".join(values), fields


def pick_labeled_amount(text: str, labels: tuple[str, ...]) -> str:
    amount_pattern = re.compile(r"(\d[\d .\u00a0]*[,.]\d{2})")
    is_vat_lookup = any(label.lower() in {"käibemaks", "kaibemaks", "vat"} or label.lower().startswith("km ") for label in labels)
    for line in text.splitlines():
        lower_line = line.lower()
        if any(label.lower() in lower_line for label in labels):
            if is_vat_lookup and re.search(r"käibemaksuta|kaibemaksuta|ilma\s+km|km-ta|without\s+vat|without\s+tax", lower_line):
                continue
            amounts = amount_pattern.findall(line)
            if amounts:
                return normalize_amount(amounts[-1])

    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        rf"(?:{label_pattern})[^\d]{{0,60}}(\d[\d .\u00a0]*[,.]\d{{2}})",
        re.IGNORECASE,
    )
    matches = pattern.findall(text)
    return normalize_amount(matches[-1]) if matches else ""


def all_text_amounts(text: str) -> list[float]:
    amounts: list[float] = []
    for match in re.findall(r"\d[\d .\u00a0]*[,.]\d{2}", text):
        amount = parse_amount(match)
        if amount is not None:
            amounts.append(amount)
    return amounts


def reconcile_gross_amount(text: str, amount_total: str, vat_amount: str) -> str:
    total = parse_amount(amount_total)
    vat = parse_amount(vat_amount)
    if total is None or vat is None or vat <= 0:
        return amount_total

    gross = round(total + vat, 2)
    for amount in all_text_amounts(text):
        if abs(amount - gross) < 0.005:
            return format_amount(gross)
    return amount_total


def pick_date(text: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"(?:{label_pattern})[^\d]{{0,40}}{DATE_RE}", re.IGNORECASE)
    match = pattern.search(text)
    return normalize_date(match.group(1)) if match else ""


def clean_issuer_name(value: str) -> str:
    name = re.split(
        r"\b(?:tel|telefon|phone|faks|fax|pank|bank|swift|iban|vat\s*no\.?|kmkr|reg\.?\s*nr\.?|registrikood|registreerimisnr\.?)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", name).strip(" :-")


def is_own_company_name(value: str) -> bool:
    return "erlin" in re.sub(r"[^0-9a-z]+", "", str(value or "").lower())


def pick_iban(text: str) -> str:
    stop_pattern = re.compile(r"\b(phone|tel|telefon|email|e-mail|vat|kmkr|reg|swift|bic)\b", re.IGNORECASE)
    for line in text.splitlines():
        if not re.search(r"\biban\b", line, re.IGNORECASE):
            continue
        tail = re.split(r"\biban\b\s*:?", line, maxsplit=1, flags=re.IGNORECASE)[-1]
        tail = stop_pattern.split(tail, maxsplit=1)[0]
        for match in IBAN_RE.finditer(tail):
            candidate = normalize_iban(match.group(0))
            if valid_iban_length(candidate):
                return candidate
    for match in IBAN_RE.finditer(text):
        candidate = normalize_iban(match.group(0))
        if valid_iban_length(candidate):
            return candidate
    return ""


def pick_invoice_number(text: str) -> str:
    series_match = re.search(
        r"\binvoice\s+series\s*:?\s*([A-Z0-9._/-]+)\s+no\.?\s*:?\s*([A-Z0-9._/-]+)",
        text,
        re.IGNORECASE,
    )
    if series_match:
        return (series_match.group(1) + series_match.group(2)).strip(" .:-")

    patterns = (
        r"\barve[-\s]*saateleht\s*nr\.?\s*:?\s*([A-Z0-9._/-]+)",
        r"\barve[-\s]*saateleht\s*:?\s*([A-Z0-9._/-]+)",
        r"\barve\s*nr\.?\s*:?\s*([A-ZÕÄÖÜ0-9._/-]+)",
        r"\barvenr\.?\s*:?\s*([A-ZÕÄÖÜ0-9._/-]+)",
        r"\barve\s+([A-Z0-9._/-]*\d[A-Z0-9._/-]*)",
        r"\binvoice\s*(?:no|nr|number)\.?\s*:?\s*([A-Z0-9._/-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .:-")
    return ""


def pick_invoice_number_from_filename(path: Path, text: str) -> str:
    normalized_text = re.sub(r"\s+", "", text).lower()
    for candidate in re.findall(r"\d{5,12}", path.stem):
        if candidate.lower() in normalized_text:
            return candidate
    return ""


def pick_issuer_name(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if re.search(r"\bseller\b.*\bbuyer\b", line, re.IGNORECASE):
            for candidate_line in lines[index + 1 : index + 5]:
                candidate = clean_issuer_name(candidate_line)
                company_match = re.match(r"^(.+?\b(?:AB|AS|OÜ|OU|UAB|SIA|GmbH|Ltd|LLC))\b", candidate, re.IGNORECASE)
                if company_match:
                    return company_match.group(1).strip()
    for index, line in enumerate(lines):
        match = re.search(
            r"^\s*(?P<name>.+?)\s+(?:registrikood|reg\.?\s*kood|reg\s*nr|reg\.?\s*no\.?|registreerimisnr\.?|registreerimis\s*nr\.?)\s*:?\s*[A-Z0-9-]{6,15}\b",
            line,
            re.IGNORECASE,
        )
        if match:
            name = clean_issuer_name(match.group("name"))
            if name and not is_own_company_name(name):
                return name
        if REG_RE.search(line):
            for previous in reversed(lines[max(0, index - 8) : index]):
                candidate = clean_issuer_name(previous)
                if is_own_company_name(candidate):
                    continue
                if not candidate or re.search(r"@|\+\d|^\d|tn\b|linn\b|tallinn|kuupäev|kuupaev", candidate, re.IGNORECASE):
                    continue
                if re.search(r"\b(AB|AS|OÜ|OU|UAB|SIA|GmbH|Ltd|LLC)\b", candidate, re.IGNORECASE):
                    return candidate
    return ""


def pick_issuer_vat_no(text: str, issuer_name: str = "") -> str:
    matches = [match.group(1).upper() for match in KMKR_RE.finditer(text)]
    if not matches:
        return ""
    if issuer_name:
        lines = [line.strip() for line in text.splitlines()]
        for index, line in enumerate(lines):
            if issuer_name.lower() in line.lower():
                window = "\n".join(lines[index : index + 8])
                match = KMKR_RE.search(window)
                if match:
                    return match.group(1).upper()
    return matches[-1]


def pick_issuer_reg_code(text: str, issuer_name: str = "") -> str:
    lines = [line.strip() for line in text.splitlines()]
    if issuer_name:
        for index, line in enumerate(lines):
            if issuer_name.lower() in line.lower():
                window = "\n".join(lines[index : index + 6])
                match = REG_RE.search(window)
                if match:
                    return match.group(1)
    for line in lines:
        match = REG_RE.search(line)
        if match and not is_own_company_name(line):
            return match.group(1)
    return ""


def pick_invoice_date_near_invoice_number(text: str) -> str:
    for line in text.splitlines():
        if re.search(r"\barve\b|\binvoice\b", line, re.IGNORECASE):
            dates = re.findall(DATE_RE, line)
            if dates:
                return normalize_date(dates[-1])
    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if re.search(r"\barve\b|\binvoice\b", line, re.IGNORECASE):
            for next_line in lines[index + 1 : index + 4]:
                if re.fullmatch(DATE_RE, next_line):
                    return normalize_date(next_line)
    return ""


def extract_from_text(text: str) -> ExtractedInvoiceFields:
    fields = ExtractedInvoiceFields(extraction_status="partial")
    compact = re.sub(r"[ \t]+", " ", text)

    fields.issuer_name = pick_issuer_name(compact)
    fields.invoice_number = pick_invoice_number(compact)
    fields.amount_total = pick_labeled_amount(
        compact,
        (
            "summa kokku",
            "arve kokku",
            "kokku tasuda",
            "tasuda",
            "tasumisele kuulub",
            "kokku",
            "total",
            "grand total",
            "payable",
        ),
    )
    fields.vat_amount = pick_labeled_amount(
        compact,
        (
            "käibemaks",
            "kaibemaks",
            "käibemaksu summa",
            "kaibemaksu summa",
            "km summa",
            "km (24%)",
            "km(24%)",
            "km 24%",
            "km 22%",
            "km 20%",
            "vat",
        ),
    )
    fields.amount_total = reconcile_gross_amount(compact, fields.amount_total, fields.vat_amount)
    fields.invoice_date = pick_date(compact, ("arve kuupäev", "arve kuupaev", "kuupäev", "kuupaev", "invoice date", "date"))
    if not fields.invoice_date:
        fields.invoice_date = pick_invoice_date_near_invoice_number(compact)
    fields.due_date = pick_date(compact, ("maksetähtaeg", "maksetahtaeg", "tasumise tähtaeg", "tasumise tahtaeg", "tähtaeg", "tahtaeg", "due date"))

    fields.payment_details = pick_iban(compact)

    fields.issuer_reg_code = pick_issuer_reg_code(compact, fields.issuer_name)
    fields.issuer_vat_no = pick_issuer_vat_no(compact, fields.issuer_name)

    found = [key for key, value in fields.as_update_fields().items() if value and key not in {"currency", "extraction_status"}]
    fields.extraction_status = "ok" if found else "no_fields_found"
    fields.extraction_note = "Leitud väljad: " + ", ".join(found) if found else "PDF/XML tekstist välju ei leitud"
    return fields


def merge_fields(primary: ExtractedInvoiceFields, extra: ExtractedInvoiceFields) -> ExtractedInvoiceFields:
    for key in ("issuer_name", "invoice_number", "amount_total", "vat_amount", "payment_details", "due_date", "invoice_date", "issuer_reg_code", "issuer_vat_no"):
        if not getattr(primary, key) and getattr(extra, key):
            setattr(primary, key, getattr(extra, key))
    primary.source_files.extend(extra.source_files)
    found = [key for key, value in primary.as_update_fields().items() if value and key not in {"currency", "extraction_status"}]
    primary.extraction_status = "ok" if found else "no_fields_found"
    primary.extraction_note = "Leitud väljad: " + ", ".join(found) if found else "PDF/XML tekstist välju ei leitud"
    return primary


def extract_from_files(paths: list[Path]) -> ExtractedInvoiceFields:
    result = ExtractedInvoiceFields(extraction_status="no_files")
    for path in paths:
        if not path.exists():
            continue
        text = ""
        xml_fields = ExtractedInvoiceFields()
        if path.suffix.lower() == ".pdf":
            text = extract_pdf_text(path)
        elif path.suffix.lower() == ".xml":
            text, xml_fields = extract_xml_text_and_fields(path)
            result = merge_fields(result, xml_fields)
        if text:
            fields = extract_from_text(text)
            if not fields.invoice_number:
                fields.invoice_number = pick_invoice_number_from_filename(path, text)
            fields.source_files.append(str(path))
            result = merge_fields(result, fields)
    return result


def split_paths(value: str) -> list[Path]:
    return [Path(part.strip()) for part in (value or "").split(";") if part.strip()]


def extract_for_db(db_path: Path, status: str = "pending", invoice_id: int | None = None, limit: int = 0) -> int:
    connection = connect(db_path)
    where = ["attachment_paths IS NOT NULL", "attachment_paths != ''"]
    params: list[object] = []
    if invoice_id is not None:
        where.append("id = ?")
        params.append(invoice_id)
    elif status != "all":
        where.append("status = ?")
        params.append(status)
    query = "SELECT * FROM invoices WHERE " + " AND ".join(where) + " ORDER BY invoice_date DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    rows = connection.execute(query, params).fetchall()
    updated = 0
    for row in rows:
        fields = extract_from_files(split_paths(row["attachment_paths"]))
        if fields.extraction_status in {"ok", "no_fields_found"}:
            apply_extracted_fields(connection, int(row["id"]), fields.as_update_fields())
            updated += 1
    return updated


def apply_extracted_fields(connection, invoice_id: int, fields: dict[str, str]) -> None:
    connection.execute(
        """
        UPDATE invoices
        SET issuer_name = CASE WHEN ? != '' THEN ? ELSE issuer_name END,
            invoice_number = CASE WHEN ? != '' THEN ? ELSE invoice_number END,
            amount_total = CASE WHEN ? != '' THEN ? ELSE amount_total END,
            vat_amount = CASE WHEN ? != '' THEN ? ELSE vat_amount END,
            payment_details = CASE WHEN ? != '' THEN ? ELSE payment_details END,
            due_date = CASE WHEN ? != '' THEN ? ELSE due_date END,
            invoice_date = CASE WHEN ? != '' THEN ? ELSE invoice_date END,
            issuer_reg_code = CASE WHEN ? != '' THEN ? ELSE issuer_reg_code END,
            issuer_vat_no = CASE WHEN ? != '' THEN ? ELSE issuer_vat_no END,
            currency = CASE WHEN ? != '' THEN ? ELSE currency END,
            extraction_status = ?,
            extraction_note = ?
        WHERE id = ?
        """,
        (
            fields.get("issuer_name", ""),
            fields.get("issuer_name", ""),
            fields.get("invoice_number", ""),
            fields.get("invoice_number", ""),
            fields.get("amount_total", ""),
            fields.get("amount_total", ""),
            fields.get("vat_amount", ""),
            fields.get("vat_amount", ""),
            fields.get("payment_details", ""),
            fields.get("payment_details", ""),
            fields.get("due_date", ""),
            fields.get("due_date", ""),
            fields.get("invoice_date", ""),
            fields.get("invoice_date", ""),
            fields.get("issuer_reg_code", ""),
            fields.get("issuer_reg_code", ""),
            fields.get("issuer_vat_no", ""),
            fields.get("issuer_vat_no", ""),
            fields.get("currency", ""),
            fields.get("currency", ""),
            fields.get("extraction_status", "not_started"),
            fields.get("extraction_note", ""),
            invoice_id,
        ),
    )
    connection.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract invoice fields from saved PDF/XML attachments.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--status", default="pending", choices=["pending", "confirmed", "rejected", "all"])
    parser.add_argument("--invoice-id", type=int)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    updated = extract_for_db(args.db, status=args.status, invoice_id=args.invoice_id, limit=args.limit)
    print(f"Uuendatud arveid: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
