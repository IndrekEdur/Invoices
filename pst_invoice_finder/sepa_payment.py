from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


SEPA_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.IGNORECASE)


@dataclass(frozen=True)
class SepaPaymentFile:
    filename: str
    xml: str
    summary: dict[str, str]
    warnings: list[str]


def row_value(row: Any, key: str) -> str:
    try:
        value = row[key]
    except Exception:
        value = row.get(key, "") if isinstance(row, dict) else ""
    return str(value or "").strip()


def parse_amount(value: str) -> Decimal:
    try:
        amount = Decimal(str(value or "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        amount = Decimal("0")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def extract_iban(value: str) -> str:
    match = IBAN_RE.search(value or "")
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(0)).upper()


def clean_text(value: str, max_length: int) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    cleaned = re.sub(r"[^\w\s.,:/+()'&-]", "", cleaned, flags=re.UNICODE)
    return cleaned[:max_length] or "NA"


def clean_id(value: str, max_length: int = 35) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9-]", "-", value or "").strip("-")
    return (cleaned or "PAYMENT")[:max_length]


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def execution_date(row: Any, today: date | None = None) -> date:
    today = today or date.today()
    due = parse_date(row_value(row, "due_date"))
    if due and due >= today:
        return due
    return today


def validate_invoice_for_payment(row: Any, debtor_iban: str) -> tuple[dict[str, str], list[str]]:
    warnings: list[str] = []
    invoice_id = row_value(row, "id")
    invoice_number = row_value(row, "invoice_number")
    creditor_name = row_value(row, "issuer_name")
    creditor_iban = extract_iban(row_value(row, "payment_details"))
    currency = row_value(row, "currency") or "EUR"
    amount = parse_amount(row_value(row, "amount_total"))

    if row_value(row, "status") != "confirmed":
        warnings.append("Arve ei ole kinnitatud. Maksefaili ei koostata enne kinnitamist.")
    if row_value(row, "invoice_kind") == "own_sales_invoice":
        warnings.append("See on ERLIN OÜ müügiarve, mitte ostuarve.")
    if row_value(row, "payment_status") == "paid":
        warnings.append("Arve on märgitud makstuks.")
    if not debtor_iban:
        warnings.append("Maksja IBAN puudub. Lisa see Meriti seadistuse vaates panga seadistuse alla.")
    if not creditor_name:
        warnings.append("Tarnija nimi puudub.")
    if not creditor_iban:
        warnings.append("Saaja IBAN puudub arve maksmise rekvisiitidest.")
    if amount <= Decimal("0"):
        warnings.append("Arve summa puudub või on null.")
    if currency != "EUR":
        warnings.append("SEPA maksefail toetab siin praegu ainult EUR valuutat.")

    summary = {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "creditor_name": creditor_name,
        "creditor_iban": creditor_iban,
        "amount": f"{amount:.2f}",
        "currency": currency,
    }
    return summary, warnings


def build_sepa_payment_xml(
    row: Any,
    *,
    debtor_name: str,
    debtor_iban: str,
    today: date | None = None,
) -> SepaPaymentFile:
    debtor_iban = extract_iban(debtor_iban)
    summary, warnings = validate_invoice_for_payment(row, debtor_iban)
    blocking = [warning for warning in warnings if not warning.startswith("Arve on märgitud makstuks.")]
    if blocking or warnings:
        raise ValueError(" ".join(warnings))

    today = today or date.today()
    created_at = datetime.now().replace(microsecond=0)
    invoice_number = summary["invoice_number"] or f"invoice-{summary['invoice_id']}"
    amount = summary["amount"]
    creditor_name = clean_text(summary["creditor_name"], 70)
    creditor_iban = summary["creditor_iban"]
    currency = summary["currency"]
    requested_date = execution_date(row, today)
    remittance_text = invoice_number if invoice_number.lower().startswith("arve") else f"Arve {invoice_number}"
    remittance = clean_text(remittance_text, 140)
    message_id = clean_id(f"AR-{summary['invoice_id']}-{created_at.strftime('%Y%m%d%H%M%S')}")
    payment_id = clean_id(f"PMT-{summary['invoice_id']}-{invoice_number}")
    end_to_end_id = clean_id(invoice_number)

    ET.register_namespace("", SEPA_NS)
    document = ET.Element(f"{{{SEPA_NS}}}Document")
    init = ET.SubElement(document, f"{{{SEPA_NS}}}CstmrCdtTrfInitn")
    group = ET.SubElement(init, f"{{{SEPA_NS}}}GrpHdr")
    ET.SubElement(group, f"{{{SEPA_NS}}}MsgId").text = message_id
    ET.SubElement(group, f"{{{SEPA_NS}}}CreDtTm").text = created_at.isoformat()
    ET.SubElement(group, f"{{{SEPA_NS}}}NbOfTxs").text = "1"
    ET.SubElement(group, f"{{{SEPA_NS}}}CtrlSum").text = amount
    initg_party = ET.SubElement(group, f"{{{SEPA_NS}}}InitgPty")
    ET.SubElement(initg_party, f"{{{SEPA_NS}}}Nm").text = clean_text(debtor_name or "ERLIN OÜ", 70)

    payment = ET.SubElement(init, f"{{{SEPA_NS}}}PmtInf")
    ET.SubElement(payment, f"{{{SEPA_NS}}}PmtInfId").text = payment_id
    ET.SubElement(payment, f"{{{SEPA_NS}}}PmtMtd").text = "TRF"
    ET.SubElement(payment, f"{{{SEPA_NS}}}BtchBookg").text = "true"
    ET.SubElement(payment, f"{{{SEPA_NS}}}NbOfTxs").text = "1"
    ET.SubElement(payment, f"{{{SEPA_NS}}}CtrlSum").text = amount
    payment_type = ET.SubElement(payment, f"{{{SEPA_NS}}}PmtTpInf")
    service_level = ET.SubElement(payment_type, f"{{{SEPA_NS}}}SvcLvl")
    ET.SubElement(service_level, f"{{{SEPA_NS}}}Cd").text = "SEPA"
    ET.SubElement(payment, f"{{{SEPA_NS}}}ReqdExctnDt").text = requested_date.isoformat()
    debtor = ET.SubElement(payment, f"{{{SEPA_NS}}}Dbtr")
    ET.SubElement(debtor, f"{{{SEPA_NS}}}Nm").text = clean_text(debtor_name or "ERLIN OÜ", 70)
    debtor_account = ET.SubElement(payment, f"{{{SEPA_NS}}}DbtrAcct")
    debtor_account_id = ET.SubElement(debtor_account, f"{{{SEPA_NS}}}Id")
    ET.SubElement(debtor_account_id, f"{{{SEPA_NS}}}IBAN").text = debtor_iban
    ET.SubElement(payment, f"{{{SEPA_NS}}}ChrgBr").text = "SLEV"

    transfer = ET.SubElement(payment, f"{{{SEPA_NS}}}CdtTrfTxInf")
    payment_id_element = ET.SubElement(transfer, f"{{{SEPA_NS}}}PmtId")
    ET.SubElement(payment_id_element, f"{{{SEPA_NS}}}EndToEndId").text = end_to_end_id
    amount_element = ET.SubElement(transfer, f"{{{SEPA_NS}}}Amt")
    instructed = ET.SubElement(amount_element, f"{{{SEPA_NS}}}InstdAmt", Ccy=currency)
    instructed.text = amount
    creditor = ET.SubElement(transfer, f"{{{SEPA_NS}}}Cdtr")
    ET.SubElement(creditor, f"{{{SEPA_NS}}}Nm").text = creditor_name
    creditor_account = ET.SubElement(transfer, f"{{{SEPA_NS}}}CdtrAcct")
    creditor_account_id = ET.SubElement(creditor_account, f"{{{SEPA_NS}}}Id")
    ET.SubElement(creditor_account_id, f"{{{SEPA_NS}}}IBAN").text = creditor_iban
    remittance_info = ET.SubElement(transfer, f"{{{SEPA_NS}}}RmtInf")
    ET.SubElement(remittance_info, f"{{{SEPA_NS}}}Ustrd").text = remittance

    xml = ET.tostring(document, encoding="utf-8", xml_declaration=True).decode("utf-8")
    filename = f"swedbank_payment_{clean_id(invoice_number, 24)}_{today.strftime('%Y%m%d')}.xml"
    summary = summary | {
        "debtor_name": debtor_name or "ERLIN OÜ",
        "debtor_iban": debtor_iban,
        "execution_date": requested_date.isoformat(),
        "remittance": remittance,
        "message_id": message_id,
    }
    return SepaPaymentFile(filename=filename, xml=xml, summary=summary, warnings=[])
