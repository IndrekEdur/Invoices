from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


STRONG_EXTENSIONS = {".pdf", ".xml", ".asice", ".bdoc", ".ddoc", ".xlsx", ".xls", ".csv"}
INVOICE_NUMBER_STOPWORDS = {
    "vaatamine",
    "tasumine",
    "tasumata",
    "eest",
    "nr",
    "number",
}
REMINDER_WORDS = (
    "meeldetuletus",
    "maksemeenutus",
    "märgukiri",
    "margukiri",
    "tasumata",
    "võlateatis",
    "volateatis",
    "üle maksetähtaja",
    "ule maksetahtaja",
)


def split_attachments(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def normalize(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"^(re|fw|fwd)\s*:\s*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def invoice_numbers(text: str) -> list[str]:
    patterns = [
        r"\barve\s*(?:nr\.?|number|#|:)?\s*([a-z0-9][a-z0-9./-]{2,})",
        r"\binvoice\s*(?:no\.?|number|#|:)?\s*([a-z0-9][a-z0-9./-]{2,})",
    ]
    found: list[str] = []
    lower = text.lower()
    for pattern in patterns:
        found.extend(match.group(1).strip(" ._-") for match in re.finditer(pattern, lower))

    for token in re.findall(r"\b[a-z]{0,6}\d[a-z0-9./-]{3,}\b", lower):
        found.append(token.strip(" ._-"))

    cleaned = []
    for number in found:
        number = number.strip(" ._-")
        for suffix in (".pdf", ".xml", ".xlsx", ".xls", ".csv"):
            if number.endswith(suffix):
                number = number[: -len(suffix)]
        cleaned.append(number)

    return sorted(
        set(
            number
            for number in cleaned
            if number
            and number not in INVOICE_NUMBER_STOPWORDS
            and any(ch.isdigit() for ch in number)
        )
    )


def strong_attachments(attachment_names: str) -> list[str]:
    result = []
    for attachment in split_attachments(attachment_names):
        suffix = Path(attachment).suffix.lower()
        if suffix in STRONG_EXTENSIONS:
            result.append(attachment)
    return result


def clean_key(row: dict[str, str]) -> str:
    attachments = [normalize(item) for item in strong_attachments(row.get("attachment_names", ""))]
    if attachments:
        return "att:" + "|".join(sorted(attachments))

    combined = " ".join([row.get("sender_name", ""), row.get("subject", "")])
    numbers = invoice_numbers(combined)
    if numbers:
        return "num:" + normalize(row.get("sender_name", "")) + "|" + "|".join(numbers)

    return "sub:" + normalize(row.get("sender_name", "")) + "|" + normalize(row.get("subject", ""))


def classify(row: dict[str, str]) -> tuple[str, int, str]:
    subject = row.get("subject", "")
    reasons = row.get("reasons", "")
    attachments = row.get("attachment_names", "")
    combined = normalize(" ".join([subject, reasons, attachments]))
    score = int(row.get("score") or 0)
    strong = strong_attachments(attachments)

    if any(word in combined for word in REMINDER_WORDS):
        return "reminder_or_debt_notice", max(0, score - 20), "contains reminder/debt wording"

    if strong:
        numbers = invoice_numbers(" ".join([subject, attachments]))
        if numbers:
            return "likely_invoice", min(100, score + 15), "strong attachment and invoice number"
        return "possible_invoice", min(100, score + 5), "strong attachment"

    if "invoice keywords" in reasons and "possible invoice number" in reasons:
        return "possible_invoice", score, "keyword and possible invoice number"

    return "needs_review", max(0, score - 10), "weak evidence"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "clean_score",
        "classification",
        "is_duplicate",
        "duplicate_key",
        "clean_note",
        "score",
        "sent_at",
        "folder",
        "sender_name",
        "sender_email",
        "subject",
        "reasons",
        "attachment_names",
        "attachment_paths",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_split_files(output_csv: Path, rows: list[dict[str, str]]) -> None:
    unique_likely = [
        row
        for row in rows
        if row["is_duplicate"] == "false" and row["classification"] == "likely_invoice"
    ]
    needs_review = [
        row
        for row in rows
        if row["is_duplicate"] == "false" and row["classification"] in {"possible_invoice", "needs_review"}
    ]
    reminders = [
        row
        for row in rows
        if row["is_duplicate"] == "false" and row["classification"] == "reminder_or_debt_notice"
    ]

    write_rows(output_csv.with_name("likely_invoices_only.csv"), unique_likely)
    write_rows(output_csv.with_name("needs_review.csv"), needs_review)
    write_rows(output_csv.with_name("reminders_and_debt_notices.csv"), reminders)


def clean_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched = []
    for row in rows:
        classification, clean_score, note = classify(row)
        row = dict(row)
        row["classification"] = classification
        row["clean_score"] = str(clean_score)
        row["clean_note"] = note
        row["duplicate_key"] = clean_key(row)
        row["is_duplicate"] = "false"
        enriched.append(row)

    enriched.sort(
        key=lambda row: (
            row["duplicate_key"],
            int(row.get("clean_score") or 0),
            row.get("sent_at", ""),
        ),
        reverse=True,
    )

    seen: set[str] = set()
    cleaned = []
    for row in enriched:
        key = row["duplicate_key"]
        if key in seen:
            row["is_duplicate"] = "true"
        else:
            seen.add(key)
        cleaned.append(row)

    cleaned.sort(
        key=lambda row: (
            row["is_duplicate"] == "true",
            row["classification"] != "likely_invoice",
            -int(row.get("clean_score") or 0),
            row.get("sent_at", ""),
        )
    )
    return cleaned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean and deduplicate invoice candidate CSV.")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args(argv)

    output_csv = args.output_csv or args.input_csv.with_name("clean_invoice_candidates.csv")
    rows = clean_rows(read_rows(args.input_csv))
    write_rows(output_csv, rows)
    write_split_files(output_csv, rows)

    kept = [row for row in rows if row["is_duplicate"] == "false"]
    likely = [row for row in kept if row["classification"] == "likely_invoice"]
    reminders = [row for row in kept if row["classification"] == "reminder_or_debt_notice"]

    print(f"Sisendridu: {len(rows)}")
    print(f"Unikaalseid ridu: {len(kept)}")
    print(f"Tõenäolisi arveid: {len(likely)}")
    print(f"Meeldetuletusi/võlateatisi: {len(reminders)}")
    print(f"Puhastatud CSV: {output_csv}")
    print(f"Ainult tõenäolised arved: {output_csv.with_name('likely_invoices_only.csv')}")
    print(f"Ülevaatamist vajavad: {output_csv.with_name('needs_review.csv')}")
    print(f"Meeldetuletused/võlateatised: {output_csv.with_name('reminders_and_debt_notices.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
