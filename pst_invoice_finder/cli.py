from __future__ import annotations

import argparse
from pathlib import Path

from .detection import make_candidate
from .pst_reader import MissingPstDependency, iter_pst_emails
from .writers import write_csv, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pst-invoice-finder",
        description="Leia Outlook PST failist võimalikud arved ja salvesta kontrolltabel.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Skanni PST fail arvekandidaatideks")
    scan.add_argument("pst_file", type=Path, help="Sisend .pst fail")
    scan.add_argument("--out-dir", type=Path, default=Path("invoice_scan_output"), help="Tulemuste kaust")
    scan.add_argument("--min-score", type=int, default=45, help="Minimaalne arvekandidaadi skoor 0-100")
    scan.add_argument("--no-attachments", action="store_true", help="Ära salvesta manuseid eraldi failidena")
    return parser


def scan_pst(args: argparse.Namespace) -> int:
    pst_file: Path = args.pst_file
    if not pst_file.exists():
        raise SystemExit(f"PST faili ei leitud: {pst_file}")

    out_dir: Path = args.out_dir
    attachments_dir = out_dir / "attachments"

    candidates = []
    total = 0
    for email in iter_pst_emails(
        pst_file,
        attachment_dir=attachments_dir,
        save_attachments=not args.no_attachments,
    ):
        total += 1
        candidate = make_candidate(email, min_score=args.min_score)
        if candidate:
            candidates.append(candidate)

    candidates.sort(key=lambda item: (item.sent_at or "", item.score), reverse=True)
    write_csv(out_dir / "invoice_candidates.csv", candidates)
    write_json(out_dir / "invoice_candidates.json", candidates)

    print(f"Loetud kirju: {total}")
    print(f"Arvekandidaate: {len(candidates)}")
    print(f"CSV: {out_dir / 'invoice_candidates.csv'}")
    print(f"JSON: {out_dir / 'invoice_candidates.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "scan":
            return scan_pst(args)
    except MissingPstDependency as exc:
        parser.exit(2, f"{exc}\n")

    parser.error("Tundmatu käsk")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
