# Architecture

This document summarizes the intended long-term architecture. For a deeper critique of the current repository and migration plan, see `ARCHITECTURE_REVIEW.md`.

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
