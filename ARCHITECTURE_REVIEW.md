# Architecture Review: Invoice Automation App

Date: 2026-06-27

Scope:

- Review the current repository and `SPECIFICATION.md`.
- Do not change existing application code.
- Describe current architecture, structural problems, target Django + PostgreSQL + HTMX architecture, migration plan, first safe implementation step, and reusable code.

## 1. Current Architecture

The current application is a local Python prototype for invoice discovery, invoice review, bank reconciliation, and Merit API integration.

It is implemented as a mostly single-process local web application:

- `web_app.py` contains the browser UI, HTTP server, API endpoints, orchestration logic, HTML, CSS, JavaScript, and much of the business workflow.
- SQLite is used as the local database.
- Filesystem folders store PST scan outputs, attachments, logs, generated CSVs, and local runtime data.
- PowerShell scripts provide convenience entry points for scanning PST files, importing bank statements, extracting invoice fields, reconciling bank data, and launching the local UI.
- Domain logic is split across several Python modules, but orchestration and view behavior remain concentrated in `web_app.py`.

The current application is useful as an MVP and knowledge capture prototype. It is not yet structured as a maintainable multi-user business application.

### 1.1 Main Runtime Flow

Current high-level flow:

1. PST or Outlook scan finds invoice candidates.
2. Candidate rows are cleaned and imported into SQLite.
3. User reviews invoices in the local browser UI.
4. PDF/XML extraction fills invoice fields.
5. Bank statements are imported from ISO XML 052 files.
6. Bank transactions are matched against local invoices.
7. Merit purchase invoices are queried through the Merit API.
8. The app compares local invoices, bank transactions, and Merit invoices.
9. Confirmed missing purchase invoices can be sent to Merit.
10. Bank-paid invoices can be checked against Merit and then marked as paid in Merit.

### 1.2 Current Modules

Current reusable modules:

- `detection.py`: email invoice candidate scoring.
- `pst_reader.py`: PST reader adapter.
- `invoice_extract.py`: PDF/XML invoice field extraction.
- `invoice_project_lines.py`: project reference and invoice line parsing.
- `bank_import.py`: ISO XML 052 bank statement parsing.
- `reconcile_bank.py`: local invoice vs bank matching.
- `compare_merit_bank_mail.py`: Merit vs bank vs mail scoring.
- `merit_api_client.py`: low-level Merit API client.
- `merit_api_payload.py`: Merit purchase invoice payload builder.
- `sepa_payment.py`: SEPA payment XML generation.
- `archive_confirmed.py`: confirmed invoice archiving.
- `invoice_db.py`: SQLite schema and database helpers.
- `web_app.py`: local UI, HTTP routing, app orchestration, embedded frontend assets.

### 1.3 Current Data Model

Current SQLite tables:

- `invoices`
- `invoice_events`
- `bank_transactions`
- `bank_import_events`
- `merit_external_payments`
- `app_settings`

The model is pragmatic but overloaded. For example, `invoices` stores:

- source metadata;
- extraction fields;
- manual review status;
- payment matching state;
- Merit send state;
- Merit payment send state;
- file paths;
- duplicate tracking.

This works for a prototype but will become difficult to reason about as workflows grow.

### 1.4 Current UI

The current UI is embedded directly inside `web_app.py` as raw HTML/CSS/JS strings.

Important views:

- consolidated list;
- Merit list;
- mail/manual invoice list;
- missing-project Merit invoices;
- bank vs Merit;
- manual invoice upload;
- bank statement upload;
- Merit settings;
- bank-paid invoices to mark paid in Merit.

The UI already captures useful workflow knowledge, but it is not modular. It should be treated as a reference implementation rather than the target frontend architecture.

## 2. Problems With Current Module and File Structure

### 2.1 `web_app.py` Is Too Large

`web_app.py` currently mixes:

- HTTP server implementation;
- routing;
- HTML templates;
- CSS;
- JavaScript;
- request parsing;
- view state;
- database access;
- domain orchestration;
- Merit API calls;
- reconciliation logic;
- streaming/SSE behavior;
- file upload handling.

This creates several risks:

- A UI change can accidentally affect business logic.
- Business rules are hard to test in isolation.
- Long functions and embedded frontend code make regression review difficult.
- Migrating to Django will be harder if this file remains the main source of truth.

Target direction:

- preserve `web_app.py` only as legacy reference during migration;
- move reusable business logic into service modules;
- rebuild UI through Django views/templates and HTMX partials.

### 2.2 SQLite Helpers Are Too Close to Application State

`invoice_db.py` creates tables and applies lightweight migrations manually.

Problems:

- no typed model layer;
- no declarative relationships;
- no database constraints beyond minimal uniqueness;
- no migration history;
- no admin interface;
- no clear separation between source records, normalized invoices, reconciliation results, and outbound API operations.

Target direction:

- Django models and migrations;
- PostgreSQL constraints and indexes;
- audit/event models for irreversible operations;
- structured settings model or environment-backed secrets.

### 2.3 Domain Concepts Are Blurred

The current `invoices` table combines several concepts:

- invoice candidate;
- accepted invoice;
- file/document;
- extraction result;
- payment status;
- Merit sync status;
- review note;
- source duplicate tracking.

This makes it harder to answer simple questions:

- Is this a scanned candidate or a confirmed invoice?
- Is this an invoice document or an accounting record?
- Is this payment status from bank matching or Merit?
- Is a Merit payment state local, live, or sent by this application?

Target direction:

- explicit domain models:
  - `Invoice`
  - `InvoiceDocument`
  - `InvoiceCandidate`
  - `ExtractionRun`
  - `BankTransaction`
  - `BankImport`
  - `MeritInvoiceSnapshot`
  - `ReconciliationMatch`
  - `PaymentCandidate`
  - `OutboundMeritOperation`
  - `Project`
  - `InvoiceLine`

### 2.4 Reconciliation Results Are Not First-Class Enough

Today, some matching state is written back onto `invoices`, some appears in generated CSVs, some is computed live, and some is shown only in UI responses.

Problems:

- difficult to audit why a match was accepted;
- difficult to compare old and new matching rules;
- difficult to rerun matching safely;
- difficult to explain automated decisions.

Target direction:

- store each reconciliation run;
- store match candidates and accepted match;
- store score, reasons, matched fields, and algorithm version;
- allow user override while keeping the automated score as evidence.

### 2.5 External Integration State Needs Stronger Modeling

Merit integration currently stores responses/errors inside invoice fields or `merit_external_payments`.

Problems:

- outbound operations need idempotency keys;
- retries need explicit state;
- "already paid in Merit" should be distinct from "payment sent by this app";
- live API results should be cached/snapshotted with timestamps;
- raw request/response should be retained for audit, but sensitive data needs handling.

Target direction:

- `OutboundMeritOperation` table:
  - operation type;
  - idempotency key;
  - payload hash;
  - request payload;
  - response payload;
  - status;
  - error;
  - created/sent/completed timestamps.
- separate `MeritInvoiceSnapshot` table for pull-based API data.

### 2.6 Filesystem Storage Is Ad Hoc

Current local paths are stored directly in rows.

Problems:

- path portability issues;
- difficult cloud/server deployment;
- harder backup strategy;
- hard to track multiple files per invoice cleanly.

Target direction:

- Django `FileField` or storage abstraction;
- structured file model;
- storage backend can initially be local filesystem, later S3-compatible object storage;
- file checksums for duplicate detection.

### 2.7 Encoding and Localization Need Cleanup

Some current source files and README output show mojibake in Estonian characters. This likely comes from PowerShell/console encoding history, not necessarily runtime logic.

Target direction:

- enforce UTF-8;
- add `.editorconfig`;
- set consistent line endings;
- keep internal code identifiers English;
- keep UI labels Estonian through templates/translations.

## 3. Target Django + PostgreSQL + HTMX Architecture

Recommended target stack:

- Django for backend, ORM, authentication, admin, forms, file handling, migrations.
- PostgreSQL for durable relational storage.
- HTMX for server-rendered interactivity.
- Celery or Django-Q/RQ for long-running tasks.
- Redis as task broker/cache if Celery is selected.
- Local filesystem storage initially; S3-compatible storage later if needed.

### 3.1 Proposed Django Apps

Recommended app split:

```text
config/
  settings.py
  urls.py

apps/
  core/
    models.py
    permissions.py
    audit.py

  documents/
    models.py
    services/storage.py
    services/fingerprints.py

  invoices/
    models.py
    views.py
    forms.py
    services/extraction.py
    services/review.py
    services/archive.py

  email_import/
    models.py
    services/pst_scan.py
    services/detection.py

  banking/
    models.py
    views.py
    services/importers.py
    services/matching.py

  merit/
    models.py
    views.py
    services/client.py
    services/payloads.py
    services/sync.py
    services/payments.py

  reconciliation/
    models.py
    views.py
    services/scoring.py
    services/runs.py

  projects/
    models.py
    services/parser.py
    services/merit_sync.py

  emta/
    models.py
    services/export.py
```

### 3.2 Suggested Core Models

#### `Invoice`

Represents the normalized business invoice.

Fields:

- direction: purchase/sales;
- status: candidate/pending_review/confirmed/rejected/exported;
- number;
- date;
- due_date;
- supplier/customer;
- totals;
- currency;
- source;
- review status;
- created/updated timestamps.

#### `InvoiceDocument`

Represents files attached to an invoice.

Fields:

- invoice FK;
- file;
- original filename;
- content type;
- checksum;
- source;
- extracted_text;
- created timestamp.

#### `ExtractionRun`

Represents one extraction attempt.

Fields:

- invoice/document FK;
- parser version;
- extracted fields JSON;
- confidence;
- warnings;
- status;
- started/completed timestamps.

#### `BankTransaction`

Represents imported bank statement rows.

Fields:

- bank import FK;
- booking date;
- value date;
- debit/credit;
- amount;
- currency;
- party name;
- party IBAN;
- remittance;
- entry ref;
- bank code;
- account IBAN;
- fingerprint unique;
- timestamps.

#### `BankImport`

Represents one uploaded statement file.

Fields:

- source file;
- import timestamp;
- statement date range;
- inserted count;
- duplicate count.

#### `MeritInvoiceSnapshot`

Represents Merit API invoice state at a point in time.

Fields:

- Merit invoice id / PIHId;
- vendor;
- bill no;
- document date;
- total;
- paid amount;
- paid status;
- raw payload JSON;
- fetched at.

#### `ReconciliationRun`

Represents a matching run.

Fields:

- type: bank_vs_local, bank_vs_merit, mail_vs_merit, consolidated;
- period;
- algorithm version;
- started/completed timestamps;
- created by;
- status.

#### `ReconciliationMatch`

Represents one proposed or accepted match.

Fields:

- run FK;
- source object type/id;
- target object type/id;
- score;
- reasons JSON;
- status: proposed/accepted/rejected/manual_override;
- accepted by;
- accepted timestamp.

#### `OutboundMeritOperation`

Represents invoice/payment/project operations sent to Merit.

Fields:

- operation type: create_invoice, create_payment, create_project;
- idempotency key;
- related invoice/payment/project;
- request JSON;
- response JSON;
- status;
- error;
- sent at;
- completed at.

### 3.3 HTMX UI Structure

Use Django templates with HTMX partial updates.

Pages:

- invoice list;
- invoice detail/review;
- manual upload;
- bank import;
- consolidated reconciliation;
- bank vs Merit;
- Merit payment candidates;
- Merit settings;
- project missing report;
- import job logs.

HTMX is a good fit because most interactions are business-table workflows, not complex client-side state applications.

Recommended patterns:

- main page renders layout and filters;
- table body loaded by HTMX;
- side detail panel loaded by HTMX;
- status buttons submit small forms;
- long operations start a job and poll job status;
- logs can use SSE or HTMX polling.

### 3.4 Long-Running Jobs

Operations that should become jobs:

- PST scan;
- bulk PDF extraction;
- bank import and reconciliation;
- Merit sync;
- Merit payment preview;
- Merit payment send;
- EMTA export generation.

Each job should have:

- status;
- progress count;
- current item label;
- structured log rows;
- error details;
- result summary.

This directly addresses the current "stuck at 50%" class of problems.

## 4. Migration Plan From Current SQLite/Local App

The safest migration is incremental. Do not rewrite everything at once.

### Phase 0: Freeze Current Prototype as Reference

Keep the current app working.

Actions:

- keep current code in Git;
- keep `SPECIFICATION.md`;
- add `ARCHITECTURE_REVIEW.md`;
- avoid large refactors in the legacy app unless needed for urgent work;
- use tests to protect extraction/scoring modules.

### Phase 1: Create Django Shell Project Alongside Current Code

Create a new Django project inside the repository without replacing the current app.

Suggested structure:

```text
legacy/
  pst_invoice_finder/   # current prototype, or keep current package as-is
django_app/
  manage.py
  config/
  apps/
```

Alternative:

```text
server/
  manage.py
  config/
  apps/
```

The first Django commit should not implement the whole product. It should prove:

- app boots;
- PostgreSQL connection works;
- one or two core models exist;
- tests run.

### Phase 2: Move Pure Domain Logic Into Reusable Services

Reuse existing pure modules with minimal changes:

- detection scoring;
- PDF/XML extraction;
- project line parsing;
- bank import parsing;
- bank/invoice scoring;
- Merit payload building;
- Merit API client.

Wrap them in Django services rather than rewriting them immediately.

### Phase 3: Build PostgreSQL Models and Import SQLite Data

Create Django models for:

- invoices;
- invoice documents;
- bank transactions;
- bank imports;
- Merit operations;
- reconciliation runs/matches.

Write a one-way migration command:

```powershell
python manage.py import_legacy_sqlite path\to\ui_register.sqlite
```

Migration should:

- import invoices;
- import bank transactions;
- import event history where possible;
- preserve original IDs in `legacy_id` fields;
- copy file references but not necessarily files at first;
- record import summary.

Do not delete or modify the SQLite database.

### Phase 4: Rebuild One Workflow at a Time

Recommended order:

1. Invoice list and detail view.
2. Manual invoice upload.
3. Bank statement import.
4. Bank vs local invoice reconciliation.
5. Merit settings and read-only Merit sync.
6. Bank vs Merit view.
7. Merit invoice send.
8. Merit payment send.
9. Project/dimension sync.
10. EMTA export.

This order creates value early while reducing risk.

### Phase 5: Replace Legacy UI

When Django supports the main daily workflows, freeze the old local UI.

The old code remains useful as:

- reference implementation;
- fallback parser library;
- regression test source.

## 5. First Safe Implementation Step

The first safe implementation step should be small, reversible, and not touch current app behavior.

Recommended first step:

> Add a new Django project skeleton with PostgreSQL settings and a first `invoices` app containing only models and tests. Do not connect it to the existing UI yet.

Concrete first commit:

1. Add Django dependencies to a new requirements file or dependency group.
2. Create Django project under `server/`.
3. Configure environment-based settings:
   - `DATABASE_URL`;
   - `SECRET_KEY`;
   - `DEBUG`;
   - `ALLOWED_HOSTS`.
4. Add initial models:
   - `Invoice`;
   - `InvoiceDocument`;
   - `BankTransaction`;
   - `BankImport`.
5. Add model tests for:
   - invoice creation;
   - bank transaction fingerprint uniqueness;
   - document checksum field.
6. Add README section explaining how to run the Django app locally.

Why this is safe:

- no legacy code changes;
- no current database mutation;
- no Merit API calls;
- no file migration yet;
- no production behavior change.

The second step should be a management command that imports a small sample from legacy SQLite into PostgreSQL.

## 6. What Should Remain Reusable From Current Code

### 6.1 Highly Reusable With Minimal Changes

These modules are mostly domain logic and should be reused:

- `detection.py`
- `invoice_project_lines.py`
- `bank_import.py`
- `compare_merit_bank_mail.py`
- `merit_api_client.py`
- `merit_api_payload.py`
- `sepa_payment.py`

They should be moved or wrapped as service modules and covered by tests.

### 6.2 Reusable After Refactoring

These modules contain valuable logic but need decoupling:

- `invoice_extract.py`
  - keep extraction heuristics;
  - split PDF text extraction, XML extraction, field normalization, and vendor detection.
- `reconcile_bank.py`
  - keep scoring ideas;
  - return structured match objects instead of directly updating DB.
- `invoice_db.py`
  - use as legacy import reference;
  - do not use as target persistence layer.

### 6.3 Mostly Legacy Reference

These should not be carried forward as architecture:

- `web_app.py`
  - keep as reference for workflows and UI behavior;
  - do not port as a monolithic module.
- PowerShell scripts
  - keep as developer convenience/reference;
  - replace production workflows with Django management commands and jobs.
- CSV output workflows
  - keep for export/debugging;
  - do not use as primary data exchange between app modules.

## 7. Suggested Target Package Boundaries

### 7.1 Domain Services

Services should be pure where possible:

- input: typed objects or dictionaries;
- output: structured results;
- no direct database writes;
- no UI assumptions.

Example:

```python
result = bank_matching.score_invoice_candidate(bank_transaction, invoice)
```

Result:

```python
{
    "score": 95,
    "reasons": ["amount", "invoice_number"],
    "matched_fields": {
        "amount": True,
        "invoice_number": True,
        "party": False,
    }
}
```

### 7.2 Application Services

Application services coordinate:

- database queries;
- domain services;
- external API calls;
- event/audit logging;
- transactions.

Example:

```python
payment_candidates = merit_payments.build_candidates(period)
```

### 7.3 Views

Django views should be thin:

- validate input;
- call application service;
- render template or return HTMX partial;
- no scoring logic inside views.

## 8. PostgreSQL Considerations

Use PostgreSQL features intentionally:

- unique constraints for fingerprints and idempotency keys;
- indexes on invoice number, supplier, date, amount;
- JSONB for raw external API payloads and match reasons;
- transaction boundaries around outbound Merit operations;
- `select_for_update` for operations that should not run twice concurrently.

Recommended indexes:

- `Invoice(number, total_amount, direction)`;
- `Invoice(date)`;
- `Invoice(status)`;
- `BankTransaction(booking_date)`;
- `BankTransaction(amount, currency)`;
- `BankTransaction(fingerprint unique)`;
- `MeritInvoiceSnapshot(bill_no, total_sum)`;
- `OutboundMeritOperation(idempotency_key unique)`;
- `ReconciliationMatch(run, score)`.

## 9. Security and Privacy

This application handles sensitive business data:

- invoices;
- bank transactions;
- supplier data;
- Merit API credentials;
- possible personal data in bank remittance text.

Target architecture must include:

- private GitHub repository;
- no real invoice/bank files in Git;
- environment variables or secret manager for API credentials;
- file upload validation;
- audit trail for external API writes;
- role-based access if more users are added;
- backup strategy for PostgreSQL and invoice documents.

Do not store Merit API keys in source files.

## 10. Recommended Near-Term Backlog

1. Add Django skeleton under `server/`.
2. Add `.env.example`.
3. Add PostgreSQL docker compose for local dev.
4. Add first Django models and migrations.
5. Add legacy SQLite import management command.
6. Port bank statement import as a Django service.
7. Port invoice list/detail with HTMX.
8. Port bank import UI.
9. Port bank reconciliation with persisted match results.
10. Port Merit read-only sync.

## 11. Final Assessment

The current system is a strong prototype because it captures many real-world business rules:

- invoice candidate scoring;
- messy PDF extraction;
- bank matching;
- Merit API edge cases;
- project reference parsing;
- live logs for slow checks;
- practical user review workflow.

The main architectural issue is not the domain logic. The main issue is that orchestration, UI, persistence, and integration state are too tightly coupled in the local app.

The best path is not a big rewrite of the algorithms. The best path is to preserve the current domain modules, move them behind Django services, and rebuild persistence/workflows around PostgreSQL, explicit models, auditability, and HTMX-based review screens.

