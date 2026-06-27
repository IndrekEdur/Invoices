from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET

from .invoice_db import connect, upsert_bank_transactions


def local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def text(node, path: str) -> str:
    current = node
    for part in path.split("/"):
        current = next((child for child in current if local(child.tag) == part), None)
        if current is None:
            return ""
    return (current.text or "").strip()


def descendants(node, name: str):
    return [child for child in node.iter() if local(child.tag) == name]


def first_desc_text(node, name: str) -> str:
    found = next((child for child in node.iter() if local(child.tag) == name and (child.text or "").strip()), None)
    return (found.text or "").strip() if found is not None else ""


def party_name(tx) -> str:
    related = next((child for child in tx.iter() if local(child.tag) == "RltdPties"), None)
    if related is None:
        return ""
    for role in ("Dbtr", "Cdtr"):
        role_node = next((child for child in related if local(child.tag) == role), None)
        if role_node is not None:
            name = text(role_node, "Nm") or text(role_node, "Pty/Nm")
            if name:
                return name
    return ""


def related_iban(tx) -> str:
    related = next((child for child in tx.iter() if local(child.tag) == "RltdPties"), None)
    if related is None:
        return ""
    for role in ("DbtrAcct", "CdtrAcct"):
        acct = next((child for child in related if local(child.tag) == role), None)
        if acct is not None:
            iban = text(acct, "Id/IBAN")
            if iban:
                return iban
    return ""


def remittance(tx) -> str:
    values = []
    for rmt in descendants(tx, "RmtInf"):
        for node_name in ("Ustrd", "Ref"):
            for node in descendants(rmt, node_name):
                value = (node.text or "").strip()
                if value:
                    values.append(value)
    return " | ".join(dict.fromkeys(values))


def parse_statement(path: Path) -> tuple[dict[str, object], list[dict[str, str]]]:
    root = ET.parse(path).getroot()
    namespace = root.tag.split("}", 1)[0].strip("{") if root.tag.startswith("{") else ""
    message_type = "unknown"
    if "camt.052" in namespace:
        message_type = "camt.052"
    elif "camt.053" in namespace:
        message_type = "camt.053"
    elif "camt.054" in namespace:
        message_type = "camt.054"

    reports = descendants(root, "Rpt")
    statements = descendants(root, "Stmt")
    containers = reports or statements
    entries: list[dict[str, str]] = []

    for container in containers:
        acct = next((child for child in container if local(child.tag) == "Acct"), container)
        account_iban = first_desc_text(acct, "IBAN")
        for ntry in descendants(container, "Ntry"):
            amt_node = next((child for child in ntry if local(child.tag) == "Amt"), None)
            amount = Decimal((amt_node.text or "0").replace(",", ".")) if amt_node is not None else Decimal("0")
            currency = amt_node.attrib.get("Ccy", "") if amt_node is not None else ""
            txs = descendants(ntry, "TxDtls") or [ntry]
            for tx in txs:
                entries.append(
                    {
                        "booking_date": text(ntry, "BookgDt/Dt") or text(ntry, "BookgDt/DtTm"),
                        "value_date": text(ntry, "ValDt/Dt") or text(ntry, "ValDt/DtTm"),
                        "credit_debit": text(ntry, "CdtDbtInd"),
                        "amount": str(amount),
                        "currency": currency,
                        "party_name": party_name(tx),
                        "party_iban": related_iban(tx),
                        "remittance": remittance(tx),
                        "entry_ref": text(ntry, "NtryRef"),
                        "bank_tx_code": first_desc_text(ntry, "Cd"),
                        "account_iban": account_iban,
                    }
                )

    dates = sorted(row["booking_date"][:10] for row in entries if row["booking_date"])
    directions = Counter(row["credit_debit"] for row in entries)
    currencies = Counter(row["currency"] for row in entries)
    statuses = Counter(text(ntry, "Sts") for ntry in descendants(root, "Ntry"))
    totals = defaultdict(Decimal)
    for row in entries:
        row_amount = Decimal(row["amount"])
        totals[(row["currency"], row["credit_debit"])] += row_amount
        totals[(row["currency"], "net")] += row_amount if row["credit_debit"] == "CRDT" else -row_amount

    summary = {
        "message_type": message_type,
        "namespace": namespace,
        "reports": len(reports),
        "statements": len(statements),
        "entries": len(entries),
        "date_from": dates[0] if dates else "",
        "date_to": dates[-1] if dates else "",
        "directions": dict(directions),
        "currencies": dict(currencies),
        "statuses": dict(statuses),
        "with_party_name": sum(1 for row in entries if row["party_name"]),
        "with_party_iban": sum(1 for row in entries if row["party_iban"]),
        "with_remittance": sum(1 for row in entries if row["remittance"]),
        "totals": {f"{currency}_{kind}": str(value) for (currency, kind), value in totals.items()},
    }
    return summary, entries


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import ISO 20022 camt bank statement to CSV and/or database.")
    parser.add_argument("xml_file", type=Path)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--db", type=Path)
    args = parser.parse_args(argv)

    summary, entries = parse_statement(args.xml_file)
    if args.output_csv:
        write_csv(args.output_csv, entries)
    db_summary = None
    if args.db:
        connection = connect(args.db)
        db_summary = upsert_bank_transactions(connection, entries, str(args.xml_file))
    print(f"Fail: {args.xml_file}")
    print(f"Tüüp: {summary['message_type']}")
    print(f"Periood: {summary['date_from']} kuni {summary['date_to']}")
    print(f"Kandeid: {summary['entries']}")
    print(f"Suund: {summary['directions']}")
    print(f"Summad: {summary['totals']}")
    if args.output_csv:
        print(f"CSV: {args.output_csv}")
    if db_summary:
        print(f"Andmebaas: {args.db}")
        print(f"Lisatud uusi kandeid: {db_summary['inserted_rows']}")
        print(f"Varem olemas: {db_summary['existing_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
