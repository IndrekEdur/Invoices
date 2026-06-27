from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

import pandas as pd


def parse_date(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text or text == "nan":
        return ""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def money(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text == "nan":
        return ""
    return text.replace(",", ".")


def payment_status(total: str, paid: str) -> str:
    try:
        total_value = float(total or 0)
        paid_value = float(paid or 0)
    except ValueError:
        return "unknown"
    if paid_value <= 0:
        return "unpaid"
    if paid_value + 0.005 >= total_value:
        return "paid"
    return "partially_paid"


def import_merit(path: Path, output_csv: Path, months: int = 6) -> list[dict[str, str]]:
    df = pd.read_excel(path, sheet_name="Ostuarved")
    today = date.today()
    cutoff = date(today.year, today.month, 1)
    month = cutoff.month - months + 1
    year = cutoff.year
    while month <= 0:
        month += 12
        year -= 1
    cutoff = date(year, month, 1)

    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        invoice_date = parse_date(row.get("Kuupäev"))
        if invoice_date:
            try:
                if datetime.fromisoformat(invoice_date).date() < cutoff:
                    continue
            except ValueError:
                pass
        total = money(row.get("Summa kokku"))
        paid = money(row.get("Tasutud summa"))
        rows.append(
            {
                "invoice_date": invoice_date,
                "amount_total": total,
                "paid_amount": paid,
                "payment_status": payment_status(total, paid),
                "supplier": str(row.get("Tarnija") or "").strip(),
                "entry_no": str(row.get("Kanne") or "").strip(),
                "invoice_number": str(row.get("Arve nr") or "").strip(),
                "posting_date": parse_date(row.get("Kande kuupäev")),
                "due_date": parse_date(row.get("Tähtaeg")),
                "currency": str(row.get("Valuuta") or "").strip(),
                "description": str(row.get("Esimese rea kirjeldus") or "").strip(),
                "has_attachment": str(row.get("Manus") or "").strip(),
                "arrived_at": parse_date(row.get("Saabus")),
                "project": str(row.get("Projekt") or "").strip(),
                "cost_center": str(row.get("Kulukoht") or "").strip(),
            }
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Merit purchase invoices Excel export.")
    parser.add_argument("xlsx_file", type=Path)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args(argv)
    rows = import_merit(args.xlsx_file, args.output_csv, months=args.months)
    print(f"Imporditud Meriti ostuarveid: {len(rows)}")
    print(f"CSV: {args.output_csv}")
    counts = {}
    for row in rows:
        counts[row["payment_status"]] = counts.get(row["payment_status"], 0) + 1
    print(f"Staatused: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
