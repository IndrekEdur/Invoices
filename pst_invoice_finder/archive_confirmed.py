from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from .invoice_db import add_event, connect


ALLOWED_EXTENSIONS = {".pdf", ".xml", ".asice", ".bdoc", ".ddoc", ".xlsx", ".xls", ".csv"}


def split_paths(value: str) -> list[Path]:
    return [Path(part.strip()) for part in (value or "").split(";") if part.strip()]


def safe_name(value: str, fallback: str = "arve") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " ._-()" else "_" for ch in (value or "")).strip()
    return cleaned or fallback


def month_parts(invoice_date: str) -> tuple[str, str]:
    if invoice_date and len(invoice_date) >= 7:
        return invoice_date[:4], invoice_date[5:7]
    return "unknown-year", "unknown-month"


def kind_folder(invoice_kind: str) -> str:
    return "muugiarved" if invoice_kind == "own_sales_invoice" else "ostuarved"


def target_filename(row, source: Path, index: int) -> str:
    invoice_number = safe_name(row["invoice_number"] or f"id-{row['id']}")
    issuer = safe_name(row["issuer_name"] or "tundmatu")
    suffix = source.suffix.lower()
    prefix = f"{invoice_number}_{issuer}"
    if index > 1:
        prefix = f"{prefix}_{index}"
    return safe_name(prefix) + suffix


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def archive_confirmed(db_path: Path, archive_root: Path, dry_run: bool = False) -> list[dict[str, str]]:
    connection = connect(db_path)
    rows = connection.execute(
        """
        SELECT *
        FROM invoices
        WHERE status = 'confirmed'
          AND attachment_paths IS NOT NULL
          AND attachment_paths != ''
        ORDER BY invoice_date, issuer_name, invoice_number
        """
    ).fetchall()

    manifest: list[dict[str, str]] = []
    for row in rows:
        year, month = month_parts(row["invoice_date"] or "")
        target_dir = archive_root / year / month / kind_folder(row["invoice_kind"] or "")
        archived_paths: list[str] = []

        source_paths = [
            path
            for path in split_paths(row["attachment_paths"])
            if path.exists() and path.suffix.lower() in ALLOWED_EXTENSIONS
        ]
        for index, source in enumerate(source_paths, start=1):
            target = unique_path(target_dir / target_filename(row, source, index))
            manifest.append(
                {
                    "invoice_id": str(row["id"]),
                    "invoice_number": row["invoice_number"] or "",
                    "invoice_date": row["invoice_date"] or "",
                    "invoice_kind": row["invoice_kind"] or "",
                    "issuer_name": row["issuer_name"] or "",
                    "source": str(source),
                    "target": str(target),
                    "copied": "false" if dry_run else "true",
                }
            )
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            archived_paths.append(str(target))

        if archived_paths and not dry_run:
            connection.execute(
                "UPDATE invoices SET archive_paths = ? WHERE id = ?",
                ("; ".join(archived_paths), row["id"]),
            )
            add_event(connection, int(row["id"]), "archived", "; ".join(archived_paths))

    if not dry_run:
        connection.commit()
    return manifest


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["invoice_id", "invoice_number", "invoice_date", "invoice_kind", "issuer_name", "source", "target", "copied"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Archive confirmed invoice files by year and month.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rows = archive_confirmed(args.db, args.archive_root, dry_run=args.dry_run)
    manifest = args.manifest or args.archive_root / "archive_manifest.csv"
    write_manifest(manifest, rows)
    print(f"Arhiveeritavaid faile: {len(rows)}")
    print(f"Arhiivi juurkaust: {args.archive_root}")
    print(f"Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
