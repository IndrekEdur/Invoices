from __future__ import annotations

import argparse
import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .invoice_db import connect, list_bank_transactions


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def amount(value: str | None) -> Decimal:
    try:
        return Decimal((value or "0").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def tokens(value: str | None) -> set[str]:
    found = set()
    for token in re.findall(r"\b[a-z]{0,8}\d[a-z0-9./-]{2,}\b", norm(value)):
        token = token.strip(" ._-")
        if any(ch.isdigit() for ch in token):
            found.add(token)
    return found


COMPANY_WORD_STOPLIST = {
    "aktsiaselts",
    "as",
    "fie",
    "mtu",
    "osauehing",
    "osauhing",
    "ou",
    "oy",
    "sa",
}


def company_name_tokens(value: str | None) -> set[str]:
    words = re.findall(r"[0-9a-z]+", norm(value))
    return {word for word in words if len(word) > 1 and word not in COMPANY_WORD_STOPLIST}


def company_names_match(first: str | None, second: str | None) -> bool:
    first_tokens = company_name_tokens(first)
    second_tokens = company_name_tokens(second)
    if not first_tokens or not second_tokens:
        return False
    overlap = first_tokens & second_tokens
    if first_tokens <= second_tokens or second_tokens <= first_tokens:
        return True
    return len(overlap) >= min(2, len(first_tokens), len(second_tokens))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_bank_from_db(db_path: Path) -> list[dict[str, str]]:
    connection = connect(db_path)
    return list_bank_transactions(connection)


def read_mail_invoices(db_path: Path) -> list[dict[str, str]]:
    connection = connect(db_path)
    rows = connection.execute(
        """
        SELECT id, status, invoice_kind, invoice_number, invoice_date, issuer_name,
               amount_total, payment_status, paid_amount, paid_date, subject, attachment_names
        FROM invoices
        WHERE invoice_kind = 'purchase_candidate'
        ORDER BY invoice_date
        """
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def match_score_merit_bank(merit: dict[str, str], bank: dict[str, str]) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    if bank.get("credit_debit") != "DBIT":
        return 0, []
    if amount(merit.get("amount_total")) and abs(amount(merit.get("amount_total")) - amount(bank.get("amount"))) <= Decimal("0.01"):
        score += 50
        reasons.append("amount")
    merit_tokens = tokens(" ".join([merit.get("invoice_number", ""), merit.get("description", "")]))
    bank_tokens = tokens(" ".join([bank.get("remittance", ""), bank.get("party_name", "")]))
    if merit.get("invoice_number") and norm(merit.get("invoice_number")) in bank_tokens:
        score += 45
        reasons.append("invoice_number")
    elif merit_tokens & bank_tokens:
        score += 35
        reasons.append("token")
    supplier = norm(merit.get("supplier"))
    party = norm(bank.get("party_name"))
    if supplier and party and (supplier in party or party in supplier or company_names_match(supplier, party)):
        score += 30
        reasons.append("party")
    return score, reasons


def match_score_merit_mail(merit: dict[str, str], mail: dict[str, str]) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    if amount(merit.get("amount_total")) and abs(amount(merit.get("amount_total")) - amount(mail.get("amount_total"))) <= Decimal("0.01"):
        score += 45
        reasons.append("amount")
    merit_tokens = tokens(" ".join([merit.get("invoice_number", ""), merit.get("description", "")]))
    mail_tokens = tokens(" ".join([mail.get("invoice_number", ""), mail.get("subject", ""), mail.get("attachment_names", "")]))
    if merit.get("invoice_number") and norm(merit.get("invoice_number")) in mail_tokens:
        score += 50
        reasons.append("invoice_number")
    elif merit_tokens & mail_tokens:
        score += 35
        reasons.append("token")
    supplier = norm(merit.get("supplier"))
    issuer = norm(mail.get("issuer_name"))
    if supplier and issuer and (supplier in issuer or issuer in supplier):
        score += 20
        reasons.append("supplier")
    return score, reasons


def best_match(item: dict[str, str], candidates: list[dict[str, str]], scorer):
    scored = []
    for candidate in candidates:
        score, reasons = scorer(item, candidate)
        if score:
            scored.append((score, "; ".join(reasons), candidate))
    if not scored:
        return None, 0, ""
    scored.sort(key=lambda row: row[0], reverse=True)
    score, reasons, candidate = scored[0]
    if score >= 50:
        return candidate, score, reasons
    return None, score, reasons


def party_conflict(merit: dict[str, str], bank: dict[str, str] | None) -> bool:
    if not bank:
        return False
    supplier = norm(merit.get("supplier"))
    party = norm(bank.get("party_name"))
    if not supplier or not party:
        return False
    return not (supplier in party or party in supplier)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def compare(
    merit_csv: Path,
    bank_csv: Path | None,
    bank_db: Path | None,
    mail_db: Path,
    out_dir: Path,
) -> dict[str, int]:
    merit_rows = read_csv(merit_csv)
    bank_rows = read_bank_from_db(bank_db) if bank_db else read_csv(bank_csv)
    mail_rows = read_mail_invoices(mail_db)

    merit_summary = []
    missing_in_mail = []
    merit_says_paid_no_bank = []
    merit_unpaid_but_bank_match = []
    supplier_bank_conflicts = []

    matched_mail_ids = set()
    matched_bank_rows = set()

    for merit in merit_rows:
        bank, bank_score, bank_reasons = best_match(merit, bank_rows, match_score_merit_bank)
        mail, mail_score, mail_reasons = best_match(merit, mail_rows, match_score_merit_mail)
        if mail:
            matched_mail_ids.add(str(mail["id"]))
        if bank:
            matched_bank_rows.add(str(bank_rows.index(bank) + 1))

        row = {
            "merit_invoice_date": merit.get("invoice_date", ""),
            "merit_supplier": merit.get("supplier", ""),
            "merit_invoice_number": merit.get("invoice_number", ""),
            "merit_amount": merit.get("amount_total", ""),
            "merit_paid_amount": merit.get("paid_amount", ""),
            "merit_payment_status": merit.get("payment_status", ""),
            "mail_invoice_id": str(mail.get("id", "")) if mail else "",
            "mail_score": str(mail_score),
            "mail_reasons": mail_reasons,
            "bank_date": bank.get("booking_date", "") if bank else "",
            "bank_amount": bank.get("amount", "") if bank else "",
            "bank_party": bank.get("party_name", "") if bank else "",
            "bank_remittance": bank.get("remittance", "") if bank else "",
            "bank_score": str(bank_score),
            "bank_reasons": bank_reasons,
        }
        merit_summary.append(row)
        if not mail:
            missing_in_mail.append(row)
        if merit.get("payment_status") in {"paid", "partially_paid"} and not bank:
            merit_says_paid_no_bank.append(row)
        if merit.get("payment_status") == "unpaid" and bank:
            merit_unpaid_but_bank_match.append(row)
        if party_conflict(merit, bank):
            supplier_bank_conflicts.append(row)

    mail_missing_in_merit = []
    for mail in mail_rows:
        if str(mail["id"]) not in matched_mail_ids:
            mail_missing_in_merit.append(
                {
                    "mail_invoice_id": str(mail["id"]),
                    "status": mail.get("status", ""),
                    "invoice_number": mail.get("invoice_number", ""),
                    "invoice_date": mail.get("invoice_date", ""),
                    "issuer_name": mail.get("issuer_name", ""),
                    "amount_total": mail.get("amount_total", ""),
                    "payment_status": mail.get("payment_status", ""),
                    "subject": mail.get("subject", ""),
                }
            )

    bank_missing_in_merit = []
    for index, bank in enumerate(bank_rows, start=1):
        if bank.get("credit_debit") == "DBIT" and str(index) not in matched_bank_rows:
            bank_missing_in_merit.append(bank)

    write_csv(out_dir / "merit_bank_mail_summary.csv", merit_summary)
    write_csv(out_dir / "merit_invoices_missing_in_mail.csv", missing_in_mail)
    write_csv(out_dir / "merit_paid_without_bank_match.csv", merit_says_paid_no_bank)
    write_csv(out_dir / "merit_unpaid_but_bank_match.csv", merit_unpaid_but_bank_match)
    write_csv(out_dir / "supplier_bank_name_conflicts.csv", supplier_bank_conflicts)
    write_csv(out_dir / "mail_invoices_missing_in_merit.csv", mail_missing_in_merit)
    write_csv(out_dir / "bank_debits_missing_in_merit.csv", bank_missing_in_merit)

    return {
        "merit_invoices": len(merit_rows),
        "bank_rows": len(bank_rows),
        "mail_purchase_invoices": len(mail_rows),
        "merit_missing_in_mail": len(missing_in_mail),
        "merit_paid_without_bank_match": len(merit_says_paid_no_bank),
        "merit_unpaid_but_bank_match": len(merit_unpaid_but_bank_match),
        "supplier_bank_name_conflicts": len(supplier_bank_conflicts),
        "mail_missing_in_merit": len(mail_missing_in_merit),
        "bank_debits_missing_in_merit": len(bank_missing_in_merit),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare Merit purchase invoices with bank and mail invoices.")
    parser.add_argument("--merit-csv", type=Path, required=True)
    parser.add_argument("--bank-csv", type=Path)
    parser.add_argument("--bank-db", type=Path)
    parser.add_argument("--mail-db", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.bank_csv and not args.bank_db:
        parser.error("one of --bank-csv or --bank-db is required")
    summary = compare(args.merit_csv, args.bank_csv, args.bank_db, args.mail_db, args.out_dir)
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(f"out_dir: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
