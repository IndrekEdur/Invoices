# Architecture

This document summarizes the intended long-term architecture. `MASTER_ARCHITECTURE.md` is the authoritative architecture document. For a deeper critique of the current repository and migration plan, see `ARCHITECTURE_REVIEW.md`.

## Current System

The current system is a local Python invoice automation prototype. It uses:

- SQLite for local persistence.
- A custom local HTTP server in `web_app.py`.
- Embedded HTML/CSS/JavaScript in `web_app.py`.
- Filesystem storage for scanned invoice attachments and generated outputs.
- PowerShell scripts for common local workflows.

The current app supports:

- PST/Outlook invoice discovery.
- PDF/XML invoice extraction.
- Manual invoice review.
- Bank statement import from ISO XML 052.
- Local bank reconciliation.
- Merit API integration.
- Merit payment marking preview/send.
- SEPA payment file generation.

## Target System

The target architecture is:

- Django backend.
- PostgreSQL database.
- HTMX frontend with Django templates.
- Background jobs for long-running imports, scans, reconciliations, and API sync.
- Explicit audit/event models for accounting-relevant decisions.

## Parallel Django Skeleton

The repository now contains a minimal Django project in `platform/`. It is intentionally separate from the legacy local app and currently provides only:

- local SQLite configuration for development;
- placeholder app packages for core, documents, accounting, integrations, learning, and workflow;
- a `/health/` JSON endpoint.

No legacy business logic or data has been migrated yet.

## Document Engine

`Document` is the root object for imported and generated files in the Django platform. Invoices, bank statements, Merit imports, EMTA exports, email attachments, and manual uploads should all start as documents before they become accounting-specific records.

The document layer stores:

- source and review status;
- original filename and file metadata;
- checksum, MIME type, size, and JSON metadata;
- document versions;
- simple tags for classification.

Future invoice, banking, Merit, and EMTA models should reference documents instead of duplicating file identity and storage fields.

## Target Django App Boundaries

Suggested apps:

- `documents`: uploaded files, checksums, extracted text.
- `invoices`: invoice domain model, review workflow, extraction state.
- `email_import`: PST/Outlook import and email candidate scoring.
- `banking`: bank imports, bank transactions, SEPA payment files.
- `merit`: Merit API client, snapshots, outbound operations.
- `reconciliation`: matching runs, match candidates, accepted matches.
- `projects`: project reference parsing and Merit dimension sync.
- `emta`: future KMD/KMD INF export workflows.

## Long-Running Operations

Long-running operations must expose progress:

- current item;
- processed count;
- total count if known;
- structured log rows;
- final summary;
- error details.

Supported UI mechanisms can include:

- HTMX polling;
- Server-Sent Events;
- background job result pages.

## Persistence Principles

PostgreSQL should store normalized domain records:

- invoices;
- invoice documents;
- bank transactions;
- Merit snapshots;
- reconciliation runs;
- reconciliation matches;
- outbound API operations;
- audit events.

Raw API payloads and match reasons can use JSONB where appropriate.

## Reuse Strategy

Reusable modules should remain framework-light where possible:

- extraction;
- scoring;
- bank parsing;
- project parsing;
- Merit payload building;
- SEPA generation.

Django views should call application services; they should not contain scoring or parsing logic directly.
