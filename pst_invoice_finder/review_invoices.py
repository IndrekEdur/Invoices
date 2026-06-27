from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from .clean_results import clean_key, invoice_numbers, strong_attachments
from .invoice_db import connect, status_counts, update_status, upsert_seen


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def first_invoice_number(row: dict[str, str]) -> str:
    numbers = invoice_numbers(" ".join([row.get("subject", ""), row.get("attachment_names", "")]))
    return numbers[0] if numbers else ""


def first_amount(row: dict[str, str]) -> str:
    text = " ".join([row.get("subject", ""), row.get("reasons", ""), row.get("attachment_names", "")])
    match = re.search(r"\b(\d+[,.]\d{2})\s*(?:eur|euro)\b", text.lower())
    return match.group(1).replace(",", ".") if match else ""


def detect_invoice_kind(row: dict[str, str]) -> str:
    subject = row.get("subject", "").lower()
    sender_name = row.get("sender_name", "").lower()
    sender_email = row.get("sender_email", "").lower()

    if (
        subject.startswith("erlin ou arve")
        or subject.startswith("erlin oü arve")
        or sender_email in {"arve@merit.ee", "noreply@merit.ee"}
        or sender_name in {"erlin ou", "erlin oü"}
    ):
        return "own_sales_invoice"

    return "purchase_candidate"


def candidate_to_data(row: dict[str, str]) -> dict[str, str]:
    attachments = strong_attachments(row.get("attachment_names", ""))
    return {
        "fingerprint": clean_key(row),
        "invoice_kind": detect_invoice_kind(row),
        "invoice_number": first_invoice_number(row),
        "invoice_date": row.get("sent_at", "")[:10],
        "issuer_name": row.get("sender_name", ""),
        "issuer_email": row.get("sender_email", ""),
        "payment_details": "",
        "amount_total": first_amount(row),
        "currency": "EUR",
        "subject": row.get("subject", ""),
        "attachment_names": row.get("attachment_names", ""),
        "attachment_paths": row.get("attachment_paths", ""),
        "source_folder": row.get("folder", ""),
        "import_source": row.get("import_source", "mail_scan") or "mail_scan",
        "review_note": "Imported from scan; strong attachments: " + "; ".join(attachments),
    }


def prompt(default: str) -> str:
    suffix = f"[{default}]" if default else ""
    value = input(f"Valik y/n/s/e/q {suffix}: ").strip().lower()
    return value or default


def edit_fields(data: dict[str, str]) -> dict[str, str]:
    editable = [
        ("invoice_number", "Arve nr"),
        ("invoice_kind", "Arve liik"),
        ("invoice_date", "Kuupaev"),
        ("issuer_name", "Valjastaja"),
        ("issuer_email", "E-post"),
        ("payment_details", "Maksmise rekvisiidid"),
        ("amount_total", "Summa"),
        ("currency", "Valuuta"),
    ]
    result = dict(data)
    for key, label in editable:
        current = result.get(key, "")
        value = input(f"{label} [{current}]: ").strip()
        if value:
            result[key] = value
    return result


def print_candidate(index: int, total: int, invoice: dict, data: dict[str, str], row: dict[str, str]) -> None:
    status = invoice["status"]
    marker = "OK previously confirmed" if status == "confirmed" else status
    print("")
    print(f"{index}/{total} - {marker}")
    print(f"Subject: {data.get('subject', '')}")
    print(f"Issuer: {data.get('issuer_name', '')} <{data.get('issuer_email', '')}>")
    print(f"Kind: {data.get('invoice_kind', '')}")
    print(f"Invoice nr: {data.get('invoice_number', '')}")
    print(f"Date: {data.get('invoice_date', '')}")
    print(f"Amount: {data.get('amount_total', '')} {data.get('currency', 'EUR')}")
    print(f"Attachments: {data.get('attachment_names', '')}")
    print(f"Classification: {row.get('classification', '')}, score {row.get('clean_score', row.get('score', ''))}")


def review(args: argparse.Namespace) -> int:
    rows = read_rows(args.input_csv)
    rows = [
        row
        for row in rows
        if row.get("is_duplicate", "false") == "false"
        and row.get("classification", "likely_invoice") in set(args.include_classification)
    ]

    if args.limit:
        rows = rows[: args.limit]

    connection = connect(args.db)
    reviewed = 0
    auto_confirmed = 0

    print(f"Andmebaas: {args.db}")
    print(f"Ulevaatamiseks ridu: {len(rows)}")
    print("Valikud: y=kinnita, n=ei ole arve/spam, s=jatka hiljem, e=muuda valju, q=lopeta")

    for index, row in enumerate(rows, start=1):
        data = candidate_to_data(row)
        invoice = upsert_seen(connection, data)

        default = "y" if invoice["status"] == "confirmed" else "s"
        if invoice["status"] == "confirmed" and args.auto_keep_confirmed:
            auto_confirmed += 1
            continue

        print_candidate(index, len(rows), dict(invoice), data, row)
        choice = prompt(default)

        if choice == "q":
            break
        if choice == "e":
            data = edit_fields({**data, **{key: invoice[key] or data.get(key, "") for key in data.keys() if key in invoice.keys()}})
            choice = prompt("y")
        if choice == "y":
            note = input("Markus kinnituse juurde (enter jatab tyhjaks): ").strip()
            update_status(connection, int(invoice["id"]), "confirmed", note=note, fields=data)
            reviewed += 1
        elif choice == "n":
            note = input("Pohjus (nt spam, pakkumine, meeldetuletus): ").strip()
            update_status(connection, int(invoice["id"]), "rejected", note=note, fields=data)
            reviewed += 1
        else:
            update_status(connection, int(invoice["id"]), "pending", note="Skipped during review", fields=data)

    counts = status_counts(connection)
    print("")
    print(f"Seekord yle vaadatud: {reviewed}")
    print(f"Automaatselt alles jaetud varem kinnitatud: {auto_confirmed}")
    print("Andmebaasi seis: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review invoice candidates and save decisions to SQLite.")
    parser.add_argument("input_csv", type=Path, help="clean_invoice_candidates.csv or likely_invoices_only.csv")
    parser.add_argument("--db", type=Path, default=Path("invoice_register.sqlite"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--include-classification",
        nargs="+",
        default=["likely_invoice"],
        choices=["likely_invoice", "possible_invoice", "needs_review", "reminder_or_debt_notice"],
    )
    parser.add_argument("--auto-keep-confirmed", action="store_true")
    args = parser.parse_args(argv)
    return review(args)


if __name__ == "__main__":
    raise SystemExit(main())
