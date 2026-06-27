from __future__ import annotations

import sqlite3
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    invoice_kind TEXT NOT NULL DEFAULT 'purchase_candidate',
    invoice_number TEXT,
    invoice_date TEXT,
    issuer_name TEXT,
    issuer_email TEXT,
    payment_details TEXT,
    amount_total TEXT,
    vat_amount TEXT,
    due_date TEXT,
    issuer_reg_code TEXT,
    issuer_vat_no TEXT,
    currency TEXT DEFAULT 'EUR',
    subject TEXT,
    attachment_names TEXT,
    attachment_paths TEXT,
    archive_paths TEXT,
    source_folder TEXT,
    import_source TEXT NOT NULL DEFAULT 'mail_scan',
    extraction_status TEXT NOT NULL DEFAULT 'not_started',
    extraction_note TEXT,
    payment_status TEXT NOT NULL DEFAULT 'unknown',
    paid_amount TEXT,
    paid_date TEXT,
    bank_match_note TEXT,
    merit_status TEXT NOT NULL DEFAULT 'not_sent',
    merit_sent_at TEXT,
    merit_response TEXT,
    merit_error TEXT,
    merit_payment_sent_at TEXT,
    merit_payment_response TEXT,
    merit_payment_error TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    confirmed_at TEXT,
    rejected_at TEXT,
    review_note TEXT
);

CREATE TABLE IF NOT EXISTS invoice_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_at TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY(invoice_id) REFERENCES invoices(id)
);

CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    booking_date TEXT,
    value_date TEXT,
    credit_debit TEXT,
    amount TEXT,
    currency TEXT,
    party_name TEXT,
    party_iban TEXT,
    remittance TEXT,
    entry_ref TEXT,
    bank_tx_code TEXT,
    account_iban TEXT,
    source_file TEXT,
    first_imported_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bank_import_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    total_rows INTEGER NOT NULL,
    inserted_rows INTEGER NOT NULL,
    existing_rows INTEGER NOT NULL,
    date_from TEXT,
    date_to TEXT
);

CREATE TABLE IF NOT EXISTS merit_external_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    invoice_number TEXT,
    supplier TEXT,
    amount TEXT,
    currency TEXT,
    paid_date TEXT,
    sent_at TEXT,
    response TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    ensure_columns(connection)
    return connection


def ensure_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(invoices)").fetchall()
    }
    if "invoice_kind" not in columns:
        connection.execute(
            "ALTER TABLE invoices ADD COLUMN invoice_kind TEXT NOT NULL DEFAULT 'purchase_candidate'"
        )
    for name in ("vat_amount", "due_date", "issuer_reg_code", "issuer_vat_no", "attachment_paths", "archive_paths", "extraction_note"):
        if name not in columns:
            connection.execute(f"ALTER TABLE invoices ADD COLUMN {name} TEXT")
    if "import_source" not in columns:
        connection.execute(
            "ALTER TABLE invoices ADD COLUMN import_source TEXT NOT NULL DEFAULT 'mail_scan'"
        )
    if "extraction_status" not in columns:
        connection.execute(
            "ALTER TABLE invoices ADD COLUMN extraction_status TEXT NOT NULL DEFAULT 'not_started'"
        )
    if "payment_status" not in columns:
        connection.execute(
            "ALTER TABLE invoices ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'unknown'"
        )
    for name in ("paid_amount", "paid_date", "bank_match_note"):
        if name not in columns:
            connection.execute(f"ALTER TABLE invoices ADD COLUMN {name} TEXT")
    if "merit_status" not in columns:
        connection.execute(
            "ALTER TABLE invoices ADD COLUMN merit_status TEXT NOT NULL DEFAULT 'not_sent'"
        )
    for name in ("merit_sent_at", "merit_response", "merit_error", "merit_payment_sent_at", "merit_payment_response", "merit_payment_error"):
        if name not in columns:
            connection.execute(f"ALTER TABLE invoices ADD COLUMN {name} TEXT")
    bank_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(bank_transactions)").fetchall()
    }
    for name in ("source_file", "first_imported_at", "last_seen_at", "seen_count"):
        if bank_columns and name not in bank_columns:
            if name == "seen_count":
                connection.execute(
                    "ALTER TABLE bank_transactions ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 1"
                )
            else:
                connection.execute(f"ALTER TABLE bank_transactions ADD COLUMN {name} TEXT")
    connection.commit()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def bank_fingerprint(row: dict[str, str]) -> str:
    parts = [
        row.get("account_iban", ""),
        row.get("entry_ref", ""),
        row.get("booking_date", "")[:10],
        row.get("value_date", "")[:10],
        row.get("credit_debit", ""),
        row.get("amount", ""),
        row.get("currency", ""),
        row.get("party_name", ""),
        row.get("party_iban", ""),
        row.get("remittance", ""),
        row.get("bank_tx_code", ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def upsert_bank_transactions(
    connection: sqlite3.Connection,
    rows: list[dict[str, str]],
    source_file: str,
) -> dict[str, int]:
    timestamp = now_iso()
    inserted = 0
    existing = 0
    dates = sorted(row.get("booking_date", "")[:10] for row in rows if row.get("booking_date"))

    for row in rows:
        fingerprint = bank_fingerprint(row)
        current = connection.execute(
            "SELECT id FROM bank_transactions WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if current:
            existing += 1
            connection.execute(
                """
                UPDATE bank_transactions
                SET last_seen_at = ?,
                    seen_count = seen_count + 1,
                    source_file = COALESCE(NULLIF(?, ''), source_file)
                WHERE fingerprint = ?
                """,
                (timestamp, source_file, fingerprint),
            )
            continue

        inserted += 1
        connection.execute(
            """
            INSERT INTO bank_transactions (
                fingerprint, booking_date, value_date, credit_debit, amount, currency,
                party_name, party_iban, remittance, entry_ref, bank_tx_code, account_iban,
                source_file, first_imported_at, last_seen_at, seen_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                fingerprint,
                row.get("booking_date", ""),
                row.get("value_date", ""),
                row.get("credit_debit", ""),
                row.get("amount", ""),
                row.get("currency", ""),
                row.get("party_name", ""),
                row.get("party_iban", ""),
                row.get("remittance", ""),
                row.get("entry_ref", ""),
                row.get("bank_tx_code", ""),
                row.get("account_iban", ""),
                source_file,
                timestamp,
                timestamp,
            ),
        )

    connection.execute(
        """
        INSERT INTO bank_import_events (
            source_file, imported_at, total_rows, inserted_rows, existing_rows, date_from, date_to
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_file,
            timestamp,
            len(rows),
            inserted,
            existing,
            dates[0] if dates else "",
            dates[-1] if dates else "",
        ),
    )
    connection.commit()
    return {
        "total_rows": len(rows),
        "inserted_rows": inserted,
        "existing_rows": existing,
    }


def list_bank_transactions(connection: sqlite3.Connection) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT booking_date, value_date, credit_debit, amount, currency, party_name,
               party_iban, remittance, entry_ref, bank_tx_code, account_iban
        FROM bank_transactions
        ORDER BY booking_date, id
        """
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def get_setting(connection: sqlite3.Connection, key: str, default: str = "") -> str:
    row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return default if row is None or row["value"] is None else str(row["value"])


def set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now_iso()),
    )
    connection.commit()


def get_settings(connection: sqlite3.Connection, keys: list[str]) -> dict[str, str]:
    return {key: get_setting(connection, key) for key in keys}


def set_settings(connection: sqlite3.Connection, values: dict[str, str]) -> None:
    timestamp = now_iso()
    for key, value in values.items():
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, timestamp),
        )
    connection.commit()


def get_invoice(connection: sqlite3.Connection, fingerprint: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM invoices WHERE fingerprint = ?",
        (fingerprint,),
    ).fetchone()


def upsert_seen(connection: sqlite3.Connection, data: dict[str, Any]) -> sqlite3.Row:
    existing = get_invoice(connection, data["fingerprint"])
    timestamp = now_iso()

    if existing:
        connection.execute(
            """
            UPDATE invoices
            SET last_seen_at = ?,
                seen_count = seen_count + 1,
                invoice_kind = COALESCE(NULLIF(?, ''), invoice_kind),
                subject = COALESCE(NULLIF(?, ''), subject),
                attachment_names = COALESCE(NULLIF(?, ''), attachment_names),
                attachment_paths = COALESCE(NULLIF(?, ''), attachment_paths),
                source_folder = COALESCE(NULLIF(?, ''), source_folder),
                import_source = COALESCE(NULLIF(?, ''), import_source),
                issuer_name = COALESCE(NULLIF(?, ''), issuer_name),
                issuer_email = COALESCE(NULLIF(?, ''), issuer_email)
            WHERE fingerprint = ?
            """,
            (
                timestamp,
                data.get("invoice_kind", ""),
                data.get("subject", ""),
                data.get("attachment_names", ""),
                data.get("attachment_paths", ""),
                data.get("source_folder", ""),
                data.get("import_source", ""),
                data.get("issuer_name", ""),
                data.get("issuer_email", ""),
                data["fingerprint"],
            ),
        )
        invoice_id = existing["id"]
        add_event(connection, invoice_id, "seen_again", "Found again in scan")
    else:
        connection.execute(
            """
            INSERT INTO invoices (
                fingerprint, status, invoice_kind, invoice_number, invoice_date, issuer_name,
                issuer_email, payment_details, amount_total, vat_amount, due_date,
                issuer_reg_code, issuer_vat_no, currency, subject, attachment_names,
                attachment_paths, source_folder, import_source, extraction_status, extraction_note,
                first_seen_at, last_seen_at, seen_count, review_note
            )
            VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                data["fingerprint"],
                data.get("invoice_kind", "purchase_candidate") or "purchase_candidate",
                data.get("invoice_number", ""),
                data.get("invoice_date", ""),
                data.get("issuer_name", ""),
                data.get("issuer_email", ""),
                data.get("payment_details", ""),
                data.get("amount_total", ""),
                data.get("vat_amount", ""),
                data.get("due_date", ""),
                data.get("issuer_reg_code", ""),
                data.get("issuer_vat_no", ""),
                data.get("currency", "EUR") or "EUR",
                data.get("subject", ""),
                data.get("attachment_names", ""),
                data.get("attachment_paths", ""),
                data.get("source_folder", ""),
                data.get("import_source", "mail_scan") or "mail_scan",
                data.get("extraction_status", "not_started") or "not_started",
                data.get("extraction_note", ""),
                timestamp,
                timestamp,
                data.get("review_note", ""),
            ),
        )
        invoice_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        add_event(connection, invoice_id, "created", "Created from scan")

    connection.commit()
    row = connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    assert row is not None
    return row


def update_status(
    connection: sqlite3.Connection,
    invoice_id: int,
    status: str,
    note: str = "",
    fields: dict[str, str] | None = None,
) -> None:
    if status not in {"pending", "confirmed", "rejected"}:
        raise ValueError(f"Invalid status: {status}")

    fields = fields or {}
    timestamp = now_iso()
    confirmed_at = timestamp if status == "confirmed" else None
    rejected_at = timestamp if status == "rejected" else None

    connection.execute(
        """
        UPDATE invoices
        SET status = ?,
            invoice_kind = COALESCE(NULLIF(?, ''), invoice_kind),
            invoice_number = COALESCE(NULLIF(?, ''), invoice_number),
            invoice_date = COALESCE(NULLIF(?, ''), invoice_date),
            issuer_name = COALESCE(NULLIF(?, ''), issuer_name),
            issuer_email = COALESCE(NULLIF(?, ''), issuer_email),
            payment_details = COALESCE(NULLIF(?, ''), payment_details),
            amount_total = COALESCE(NULLIF(?, ''), amount_total),
            vat_amount = COALESCE(NULLIF(?, ''), vat_amount),
            due_date = COALESCE(NULLIF(?, ''), due_date),
            issuer_reg_code = COALESCE(NULLIF(?, ''), issuer_reg_code),
            issuer_vat_no = COALESCE(NULLIF(?, ''), issuer_vat_no),
            currency = COALESCE(NULLIF(?, ''), currency),
            attachment_paths = COALESCE(NULLIF(?, ''), attachment_paths),
            extraction_status = COALESCE(NULLIF(?, ''), extraction_status),
            extraction_note = COALESCE(NULLIF(?, ''), extraction_note),
            confirmed_at = CASE WHEN ? IS NULL THEN confirmed_at ELSE ? END,
            rejected_at = CASE WHEN ? IS NULL THEN rejected_at ELSE ? END,
            review_note = COALESCE(NULLIF(?, ''), review_note)
        WHERE id = ?
        """,
        (
            status,
            fields.get("invoice_kind", ""),
            fields.get("invoice_number", ""),
            fields.get("invoice_date", ""),
            fields.get("issuer_name", ""),
            fields.get("issuer_email", ""),
            fields.get("payment_details", ""),
            fields.get("amount_total", ""),
            fields.get("vat_amount", ""),
            fields.get("due_date", ""),
            fields.get("issuer_reg_code", ""),
            fields.get("issuer_vat_no", ""),
            fields.get("currency", ""),
            fields.get("attachment_paths", ""),
            fields.get("extraction_status", ""),
            fields.get("extraction_note", ""),
            confirmed_at,
            confirmed_at,
            rejected_at,
            rejected_at,
            note,
            invoice_id,
        ),
    )
    add_event(connection, invoice_id, status, note)
    connection.commit()


def add_event(connection: sqlite3.Connection, invoice_id: int, event_type: str, note: str = "") -> None:
    connection.execute(
        "INSERT INTO invoice_events (invoice_id, event_type, event_at, note) VALUES (?, ?, ?, ?)",
        (invoice_id, event_type, now_iso(), note),
    )


def status_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        "SELECT status, COUNT(*) AS count FROM invoices GROUP BY status ORDER BY status"
    ).fetchall()
    return {row["status"]: int(row["count"]) for row in rows}
