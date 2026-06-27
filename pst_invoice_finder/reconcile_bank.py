from __future__ import annotations

import argparse
import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .invoice_db import connect


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def amount(value: str | None) -> Decimal:
    try:
        return Decimal((value or "0").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def invoice_tokens(value: str | None) -> set[str]:
    value = norm(value)
    tokens: set[str] = set()
    for token in re.findall(r"\b[a-z]{0,8}\d[a-z0-9./-]{2,}\b", value):
        token = token.strip(" ._-")
        for suffix in (".pdf", ".xml"):
            if token.endswith(suffix):
                token = token[: -len(suffix)]
        if any(ch.isdigit() for ch in token):
            tokens.add(token)
    return tokens


def read_bank(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_invoices(db_path: Path) -> list[dict[str, str]]:
    connection = connect(db_path)
    rows = connection.execute(
        """
        SELECT id, status, invoice_kind, invoice_number, invoice_date, issuer_name,
               payment_details, amount_total, currency, subject, attachment_names,
               archive_paths, attachment_paths
        FROM invoices
        WHERE status != 'rejected'
        ORDER BY invoice_date, issuer_name
        """
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def invoice_match_score(bank: dict[str, str], invoice: dict[str, str]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    bank_amount = amount(bank.get("amount"))
    invoice_amount = amount(invoice.get("amount_total"))
    if invoice_amount and abs(bank_amount - invoice_amount) <= Decimal("0.01"):
        score += 50
        reasons.append("amount")

    bank_iban = digits(bank.get("party_iban"))
    invoice_iban = digits(invoice.get("payment_details"))
    if invoice_iban and bank_iban and invoice_iban == bank_iban:
        score += 35
        reasons.append("iban")

    bank_tokens = invoice_tokens(" ".join([bank.get("remittance", ""), bank.get("party_name", "")]))
    invoice_number = norm(invoice.get("invoice_number"))
    invoice_tokens_all = invoice_tokens(" ".join([invoice.get("invoice_number", ""), invoice.get("subject", ""), invoice.get("attachment_names", "")]))
    if invoice_number and invoice_number in bank_tokens:
        score += 45
        reasons.append("invoice_number")
    elif bank_tokens & invoice_tokens_all:
        score += 35
        reasons.append("token")

    party = norm(bank.get("party_name"))
    issuer = norm(invoice.get("issuer_name"))
    if party and issuer and (party in issuer or issuer in party):
        score += 20
        reasons.append("party_name")

    return score, reasons


def best_match(bank: dict[str, str], invoices: list[dict[str, str]]) -> tuple[dict[str, str] | None, int, str]:
    candidates = []
    for invoice in invoices:
        if bank["credit_debit"] == "DBIT" and invoice.get("invoice_kind") != "purchase_candidate":
            continue
        if bank["credit_debit"] == "CRDT" and invoice.get("invoice_kind") != "own_sales_invoice":
            continue
        score, reasons = invoice_match_score(bank, invoice)
        if score:
            candidates.append((score, "; ".join(reasons), invoice))
    if not candidates:
        return None, 0, ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    score, reasons, invoice = candidates[0]
    if score >= 50:
        return invoice, score, reasons
    return None, score, reasons


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def reconcile(bank_csv: Path, db_path: Path, out_dir: Path) -> dict[str, int]:
    bank_rows = read_bank(bank_csv)
    invoices = read_invoices(db_path)
    connection = connect(db_path)
    matched_invoice_ids: set[str] = set()
    missing_purchase_docs: list[dict[str, str]] = []
    missing_sales_docs: list[dict[str, str]] = []
    matched: list[dict[str, str]] = []

    for idx, bank in enumerate(bank_rows, start=1):
        invoice, score, reasons = best_match(bank, invoices)
        if invoice:
            matched_invoice_ids.add(str(invoice["id"]))
            connection.execute(
                """
                UPDATE invoices
                SET payment_status = 'paid',
                    paid_amount = ?,
                    paid_date = ?,
                    bank_match_note = ?
                WHERE id = ?
                """,
                (
                    bank["amount"],
                    bank["booking_date"][:10],
                    f"Bank row {idx}; score {score}; {reasons}",
                    invoice["id"],
                ),
            )
            matched.append(
                {
                    "bank_row": str(idx),
                    "booking_date": bank["booking_date"],
                    "direction": bank["credit_debit"],
                    "bank_amount": bank["amount"],
                    "party_name": bank["party_name"],
                    "remittance": bank["remittance"],
                    "invoice_id": str(invoice["id"]),
                    "invoice_number": invoice.get("invoice_number", ""),
                    "invoice_date": invoice.get("invoice_date", ""),
                    "invoice_amount": invoice.get("amount_total", ""),
                    "score": str(score),
                    "reasons": reasons,
                }
            )
        else:
            row = {
                "bank_row": str(idx),
                "booking_date": bank["booking_date"],
                "amount": bank["amount"],
                "currency": bank["currency"],
                "party_name": bank["party_name"],
                "party_iban": bank["party_iban"],
                "remittance": bank["remittance"],
                "best_weak_score": str(score),
                "best_weak_reasons": reasons,
            }
            if bank["credit_debit"] == "DBIT":
                missing_purchase_docs.append(row)
            else:
                missing_sales_docs.append(row)

    invoice_without_bank: list[dict[str, str]] = []
    for invoice in invoices:
        if str(invoice["id"]) in matched_invoice_ids:
            continue
        if invoice.get("status") == "confirmed":
            connection.execute(
                """
                UPDATE invoices
                SET payment_status = CASE WHEN payment_status = 'paid' THEN payment_status ELSE 'unmatched' END
                WHERE id = ?
                """,
                (invoice["id"],),
            )
        invoice_without_bank.append(
            {
                "invoice_id": str(invoice["id"]),
                "status": invoice["status"],
                "invoice_kind": invoice["invoice_kind"],
                "invoice_number": invoice.get("invoice_number", ""),
                "invoice_date": invoice.get("invoice_date", ""),
                "issuer_name": invoice.get("issuer_name", ""),
                "amount_total": invoice.get("amount_total", ""),
                "payment_details": invoice.get("payment_details", ""),
                "subject": invoice.get("subject", ""),
            }
        )

    write_csv(out_dir / "matched_bank_invoice_rows.csv", matched)
    write_csv(out_dir / "bank_debits_missing_purchase_invoice.csv", missing_purchase_docs)
    write_csv(out_dir / "bank_credits_missing_sales_invoice.csv", missing_sales_docs)
    write_csv(out_dir / "system_invoices_without_bank_match.csv", invoice_without_bank)
    connection.commit()

    return {
        "bank_rows": len(bank_rows),
        "system_invoices": len(invoices),
        "matched": len(matched),
        "bank_debits_missing_purchase_invoice": len(missing_purchase_docs),
        "bank_credits_missing_sales_invoice": len(missing_sales_docs),
        "system_invoices_without_bank_match": len(invoice_without_bank),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile bank transactions against invoice register.")
    parser.add_argument("--bank-csv", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = reconcile(args.bank_csv, args.db, args.out_dir)
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(f"out_dir: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
