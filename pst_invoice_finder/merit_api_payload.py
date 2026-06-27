from __future__ import annotations

import base64
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .invoice_project_lines import ProjectInvoiceLine, parse_project_lines_from_attachments


DEFAULT_ITEM_CODE = "alltöö"
DEFAULT_ITEM_DESCRIPTION = "Alltöövõtutööd"
DEFAULT_GL_ACCOUNT_CODE = "4009"
DEFAULT_PAYMENT_METHOD = "Pank"
TAX_ID_PLACEHOLDER = "MERIT_TAX_ID_TULEB_GETTAXES_ENDPOINTIST"


def parse_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def merit_date(value: str | None, with_time: bool = False) -> str:
    text = (value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        date = "".join(match.groups())
    else:
        date = re.sub(r"\D+", "", text)[:8]
    return f"{date}0000" if with_time and date else date


def split_paths(value: str | None) -> list[Path]:
    if not value:
        return []
    return [Path(part.strip()) for part in re.split(r";|\|", value) if part.strip()]


def first_pdf_attachment(value: str | None) -> Path | None:
    for path in split_paths(value):
        if path.suffix.lower() == ".pdf" and path.exists():
            return path
    return None


def row_value(row: Any, key: str) -> str:
    try:
        value = row[key]
    except (KeyError, IndexError):
        value = ""
    return "" if value is None else str(value)


def build_purchase_invoice_payload(
    row: Any,
    include_attachment_content: bool = False,
    item_code: str = DEFAULT_ITEM_CODE,
    payment_method: str = DEFAULT_PAYMENT_METHOD,
    tax_id: str = TAX_ID_PLACEHOLDER,
    gl_account_code: str = DEFAULT_GL_ACCOUNT_CODE,
    project_dimension_id: int | None = None,
    project_values: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gross = parse_decimal(row_value(row, "amount_total"))
    vat = parse_decimal(row_value(row, "vat_amount"))
    net = gross - vat if vat else gross
    currency = row_value(row, "currency") or "EUR"
    due_date = row_value(row, "due_date") or row_value(row, "invoice_date")
    paid_amount = parse_decimal(row_value(row, "paid_amount"))
    paid_date = row_value(row, "paid_date")
    attachment = first_pdf_attachment(row_value(row, "attachment_paths"))
    project_lines = parse_project_lines_from_attachments(row_value(row, "attachment_paths"))
    project_values = project_values or {}
    warnings: list[str] = []

    if not row_value(row, "invoice_number"):
        warnings.append("Arve number puudub.")
    if not row_value(row, "issuer_name"):
        warnings.append("Tarnija nimi puudub.")
    if not row_value(row, "issuer_reg_code"):
        warnings.append("Tarnija registrikood puudub.")
    if not vat:
        warnings.append("KM summa puudub; TaxAmount on 0 ja TaxId vajab käsitsi kontrolli.")
    if not paid_amount or not paid_date:
        warnings.append("Pangamakse info puudub või arve pole pangaga makstuks märgitud.")
    if tax_id == TAX_ID_PLACEHOLDER:
        warnings.append("TaxId tuleb enne päris saatmist küsida Meriti gettaxes endpointist.")
    warnings.append("Item.Code peab Meritis olemas olema või tuleb seadistada õige kuluartikkel/konto.")
    warnings.append("PaymentMethod peab Meritis olemas olema; kontrolli getpaymenttypes vastusest.")
    if project_lines and not project_dimension_id:
        warnings.append("PDF-ist leiti projektiridu, aga Meriti projekti dimensiooni ID puudub.")

    invoice_rows = build_invoice_rows(
        row,
        project_lines=project_lines,
        item_code=item_code,
        tax_id=tax_id,
        gl_account_code=gl_account_code,
        fallback_net=net,
        project_dimension_id=project_dimension_id,
        project_values=project_values,
    )

    payload: dict[str, Any] = {
        "Vendor": {
            "Name": row_value(row, "issuer_name"),
            "RegNo": row_value(row, "issuer_reg_code"),
            "VatAccountable": bool(row_value(row, "issuer_vat_no")),
            "VatRegNo": row_value(row, "issuer_vat_no"),
            "CurrencyCode": currency,
            "CountryCode": "EE",
            "Email": row_value(row, "issuer_email"),
        },
        "ExpenseClaim": False,
        "DocDate": merit_date(row_value(row, "invoice_date")),
        "DueDate": merit_date(due_date),
        "TransactionDate": merit_date(row_value(row, "invoice_date")),
        "BillNo": row_value(row, "invoice_number"),
        "CurrencyCode": currency,
        "BankAccount": row_value(row, "payment_details"),
        "InvoiceRow": invoice_rows,
        "TaxAmount": [
            {
                "TaxId": tax_id,
                "Amount": money(vat),
            }
        ],
        "TotalAmount": money(net),
        "Hcomment": "Imporditud e-mailist arveregistri kaudu.",
        "Fcomment": row_value(row, "bank_match_note"),
    }

    if paid_amount and paid_date:
        payload["Payment"] = {
            "PaymentMethod": payment_method or DEFAULT_PAYMENT_METHOD,
            "PaidAmount": money(paid_amount),
            "PaymDate": merit_date(paid_date, with_time=True),
        }

    attachment_info: dict[str, Any] = {"included": False}
    if attachment:
        encoded = base64.b64encode(attachment.read_bytes()).decode("ascii")
        payload["Attachment"] = {
            "FileName": attachment.name,
            "FileContent": encoded if include_attachment_content else f"<base64 PDF content, {len(encoded)} chars>",
        }
        attachment_info = {
            "included": True,
            "filename": attachment.name,
            "path": str(attachment),
            "base64_length": len(encoded),
        }
    else:
        warnings.append("PDF manust ei leitud; Meritisse saatmisel Attachment puuduks.")

    return {
        "endpoint": "https://aktiva.merit.ee/api/v2/sendpurchinvoice",
        "method": "POST",
        "payload": payload,
        "human_summary": {
            "vendor_name": row_value(row, "issuer_name"),
            "vendor_reg_no": row_value(row, "issuer_reg_code"),
            "vendor_vat_no": row_value(row, "issuer_vat_no"),
            "invoice_number": row_value(row, "invoice_number"),
            "invoice_date": row_value(row, "invoice_date"),
            "due_date": due_date,
            "transaction_date": row_value(row, "invoice_date"),
            "currency": currency,
            "net_amount": money(net),
            "vat_amount": money(vat),
            "gross_amount": money(gross),
            "payment_status": "Makstud" if paid_amount and paid_date else "Makse puudub eelvaates",
            "paid_amount": money(paid_amount),
            "paid_date": paid_date,
            "payment_method": (payment_method or DEFAULT_PAYMENT_METHOD) if paid_amount and paid_date else "",
            "bank_account": row_value(row, "payment_details"),
            "item_code": item_code or DEFAULT_ITEM_CODE,
            "gl_account_code": gl_account_code or DEFAULT_GL_ACCOUNT_CODE,
            "item_description": row_value(row, "subject") or DEFAULT_ITEM_DESCRIPTION,
            "project_rows_count": len(project_lines),
            "project_codes": ", ".join(line.project_code for line in project_lines),
            "tax_id": tax_id,
            "attachment_filename": attachment.name if attachment else "",
            "attachment_included": bool(attachment),
        },
        "warnings": warnings,
        "attachment": attachment_info,
    }


def build_invoice_rows(
    row: Any,
    *,
    project_lines: list[ProjectInvoiceLine],
    item_code: str,
    tax_id: str,
    gl_account_code: str,
    fallback_net: Decimal,
    project_dimension_id: int | None,
    project_values: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not project_lines:
        description = row_value(row, "subject") or DEFAULT_ITEM_DESCRIPTION
        invoice_row = {
                "Item": {
                    "Code": item_code or DEFAULT_ITEM_CODE,
                    "Description": description[:100],
                    "Type": 2,
                },
                "Quantity": 1,
                "Price": money(fallback_net),
                "TaxId": tax_id,
                "Description": description[:100],
        }
        if gl_account_code:
            invoice_row["GLAccountCode"] = gl_account_code
        return [invoice_row]

    rows: list[dict[str, Any]] = []
    for line in project_lines:
        description = line.description[:100]
        price = line.unit_price or line.net_amount
        if not price and len(project_lines) == 1:
            price = fallback_net
        invoice_row: dict[str, Any] = {
            "Item": {
                "Code": item_code or DEFAULT_ITEM_CODE,
                "Description": description,
                "Type": 2,
            },
            "Quantity": float(line.quantity),
            "Price": money(price),
            "TaxId": tax_id,
            "Description": description,
        }
        if gl_account_code:
            invoice_row["GLAccountCode"] = gl_account_code
        value = project_values.get(line.project_code, {})
        if project_dimension_id:
            dimension: dict[str, Any] = {
                "DimId": int(project_dimension_id),
                "DimCode": line.project_code,
            }
            if value.get("Id"):
                dimension["DimValueId"] = value["Id"]
            invoice_row["Dimensions"] = [dimension]
        rows.append(invoice_row)
    return rows
