from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .invoice_db import connect


FIELDS = [
    "id",
    "status",
    "invoice_kind",
    "invoice_number",
    "invoice_date",
    "issuer_name",
    "issuer_email",
    "payment_details",
    "amount_total",
    "vat_amount",
    "due_date",
    "issuer_reg_code",
    "issuer_vat_no",
    "currency",
    "subject",
    "attachment_names",
    "attachment_paths",
    "source_folder",
    "extraction_status",
    "extraction_note",
    "payment_status",
    "paid_amount",
    "paid_date",
    "bank_match_note",
    "first_seen_at",
    "last_seen_at",
    "seen_count",
    "confirmed_at",
    "rejected_at",
    "review_note",
    "fingerprint",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export invoice SQLite register to CSV.")
    parser.add_argument("--db", type=Path, default=Path("invoice_register.sqlite"))
    parser.add_argument("--output-csv", type=Path, default=Path("invoice_register_export.csv"))
    args = parser.parse_args(argv)

    connection = connect(args.db)
    rows = connection.execute(
        """
        SELECT id, status, invoice_kind, invoice_number, invoice_date, issuer_name, issuer_email,
               payment_details, amount_total, vat_amount, due_date, issuer_reg_code,
               issuer_vat_no, currency, subject, attachment_names, attachment_paths,
               source_folder, extraction_status, extraction_note, payment_status,
               paid_amount, paid_date, bank_match_note, first_seen_at,
               last_seen_at, seen_count, confirmed_at, rejected_at, review_note, fingerprint
        FROM invoices
        ORDER BY invoice_date DESC, issuer_name, invoice_number
        """
    ).fetchall()

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in FIELDS})

    print(f"Eksporditud ridu: {len(rows)}")
    print(f"CSV: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
