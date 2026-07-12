# Project Financial Reporting Architecture

This document defines how the Operations Workspace Platform imports, stores, reconciles, aggregates, explains, and distributes project financial data from Merit Aktiva.

It follows `PLATFORM_ARCHITECTURE.md`, `MASTER_ARCHITECTURE.md`, `ENTERPRISE_DOMAIN_MAP.md`, `PROJECT_ARCHITECTURE.md`, `COMMUNICATION_ARCHITECTURE.md`, `KNOWLEDGE_ARCHITECTURE.md`, `MERIT_INTEGRATION_ARCHITECTURE.md`, `SETTINGS_ARCHITECTURE.md`, `MVP_ROADMAP.md`, and `ENGINEERING_GUIDE.md`.

## Architecture And Duplication Review

Financial reporting must extend existing platform identities instead of creating duplicates.

Existing objects and services to reuse:

- `Organization` remains the tenant boundary for all imported accounting data.
- `AccountingIntegration` remains the provider configuration for Merit and future accounting connectors.
- `MeritAPIClient` remains the only component that knows Merit endpoint paths and direct HTTP behavior.
- `MeritAuthenticationService` and `SecretProvider` remain the authentication and secret boundaries.
- `AccountingDimension` remains the local cache for Merit dimensions, especially project dimension values.
- `AccountingDimensionSyncService`, `AccountingDimensionValueService`, and `ProjectCodeAllocationService` remain the dimension/project-code integration layer.
- `Project` remains the primary business context; financial records link to projects through allocations and dimension values, not through duplicated project rows.
- `ProjectParty` remains the current lightweight project recipient/contact concept until a global Party model exists.
- `ProjectKnowledgeBuilder` remains the future way to assemble project context for Workspace and AI.
- `Document`, `DocumentVersion`, and `DocumentStorageService` remain the source-document identity and storage boundary.
- `EmailMessage`, `EmailAttachment`, and `EmailAttachmentDocumentService` remain the communication origin and attachment-to-document conversion boundary.
- `AuditEvent` remains the compliance and traceability record.
- `WorkflowInstance` and `WorkflowEvent` remain process execution history, not accounting facts.

Do not introduce duplicate invoice, payment, document, or project identities:

- A future accounting invoice cache is a synchronized Merit read model, not a replacement for `Document`.
- A future source-document match links Merit invoice records to `Document` and `EmailAttachment`; it does not copy file identity into accounting rows.
- A future payment cache is accounting/payment evidence; it does not replace bank statement or bank transaction identities.
- A project financial report links to `Project` and allocation data; it does not create a second project registry.

## 1. Vision

The Workspace is not the accounting system of record.

Merit remains the accounting authority. Workspace creates a synchronized operational read model that makes Merit accounting data useful inside project work: project financial reporting, invoice/document reconciliation, alerts, explainable management information, and controlled report distribution.

Financial information must remain:

- traceable to source records;
- reproducible from sync runs, allocations, account mappings, and period rules;
- period-aware;
- organization-scoped;
- linked to projects, documents, communications, payments, workflow, and audit records.

Workspace must not rewrite accounting history. It reads, caches, reconciles, aggregates, explains, and prepares review workflows.

## 2. Primary Business Questions

The architecture must support questions such as:

- What is the financial result of project 26124 this month?
- How much revenue and cost has the project accumulated?
- Which months were negative?
- Has a sales invoice been issued this month?
- Are there costs but no revenue?
- Which purchase invoices exist in e-mail but not in Merit?
- Which Merit invoices have no source document?
- Which invoices are unpaid?
- Which bank payments cannot be matched to invoices?
- Which transactions have no project dimension?
- Which project managers should receive which reports?

Each answer should include source references, period rules, and data quality warnings where relevant.

## 3. Financial Source Layers

Financial data has four separate source layers. They must not be collapsed into one generic accounting row without preserving source semantics.

### A. General Ledger Transactions

Purpose:

- accounting truth for revenue, cost, result, and corrections;
- account-based classification;
- project dimension allocations;
- monthly aggregation.

Source:

- Merit `GetGLBatchesFull` or the corresponding official full-detail general-ledger endpoint.

### B. Sales Invoices

Purpose:

- concrete outgoing invoice identity;
- invoice date, customer, due date, VAT, amount, payments, and project allocations;
- detection of months without revenue invoices.

Sales invoices answer whether billing happened. They should not be the only source for final profitability.

### C. Purchase Invoices

Purpose:

- concrete supplier invoice identity;
- supplier, invoice number, document date, VAT, due date, and project allocations;
- comparison with e-mail attachments and Documents.

Purchase invoices provide reconciliation targets between Merit, e-mail evidence, documents, and payments.

### D. Payments And Bank Data

Purpose:

- paid/unpaid state;
- partial payments;
- payment date;
- bank account and counterparty evidence;
- invoice reconciliation and unmatched bank transactions.

Payment evidence may come from Merit payment records, imported bank statements, and future direct bank integrations.

## 4. Source-Of-Truth Rules

Rules:

- Merit GL is the accounting truth for booked revenue, cost, and result.
- Merit invoice records are the truth for whether an invoice exists in accounting.
- Payment records and bank statements are the truth for payment evidence.
- E-mail attachments and Documents are source-document evidence.
- Workspace aggregation does not rewrite accounting history.
- Manual Workspace classification must not silently change Merit data.
- User-confirmed Workspace links improve reconciliation and reporting, but external accounting writes require explicit service-layer actions and audit.

## 5. Proposed Domain Concepts

These are architectural proposals only. Do not add models in this task.

### AccountingSyncRun

Identity: one execution of one financial sync source for one integration.
Source system: Workspace.
External ID: optional provider run id if available.
Organization: required.
Project relation: indirect through imported records.
Accounting period: optional source period window.
Changed/source updated time: stores started, completed, cursor, and source window.
Raw payload retention: summary only; raw records belong to individual cached records where needed.
Audit expectations: sync started, completed, failed, counts, safe errors.

### AccountingTransaction

Identity: Merit GL batch or accounting transaction header.
Source system: Merit.
External ID: integration plus external batch/transaction id.
Organization: required.
Project relation: through lines and allocations.
Accounting period: posting period.
Changed/source updated time: source changed date where available.
Raw payload retention: retained for debugging, not as UI truth.
Audit expectations: synced through sync run.

### AccountingTransactionLine

Identity: batch external id plus line external id or deterministic line key.
Source system: Merit.
External ID: stable line id or deterministic source key.
Organization: required.
Project relation: through allocations.
Accounting period: posting date/period.
Changed/source updated time: inherited from transaction or line.
Raw payload retention: line raw payload for traceability.
Audit expectations: source sync only; manual classification changes require separate audit.

### AccountingAllocation

Identity: parent source id plus dimension id, dimension value code, amount, and sequence where needed.
Source system: Merit or Workspace confirmed allocation where external source lacks detail.
External ID: provider allocation id if available, otherwise deterministic key.
Organization: required.
Project relation: links to `Project` through project dimension code when matched.
Accounting period: inherited from parent accounting line.
Changed/source updated time: inherited or own source changed date.
Raw payload retention: dimension/allocation payload.
Audit expectations: allocation mapping changes are audited.

### AccountingInvoice

Identity: integration plus Merit invoice GUID.
Source system: Merit.
External ID: Merit sales or purchase invoice GUID.
Organization: required.
Project relation: through invoice allocations/lines.
Accounting period: invoice date and posting date remain separate.
Changed/source updated time: Merit changed date where available.
Raw payload retention: invoice header and source summary.
Audit expectations: sync and manual reconciliation changes audited.

### AccountingInvoiceLine

Identity: invoice external id plus line id or deterministic line key.
Source system: Merit.
External ID: provider line id if available.
Organization: required.
Project relation: line allocations.
Accounting period: inherited from invoice/posting policy.
Changed/source updated time: inherited from invoice.
Raw payload retention: line-level payload for audit and debugging.
Audit expectations: no hidden user changes.

### AccountingInvoiceAllocation

Identity: invoice line plus dimension value plus amount/sequence.
Source system: Merit.
External ID: provider allocation id if available.
Organization: required.
Project relation: link to `Project` via `AccountingDimension.code` and `Project.code`.
Accounting period: inherited from invoice line.
Changed/source updated time: inherited.
Raw payload retention: allocation payload.
Audit expectations: mapping conflicts and manual links audited.

### AccountingPayment

Identity: integration plus payment GUID.
Source system: Merit, bank import, or future bank API, with source type preserved.
External ID: provider payment id.
Organization: required.
Project relation: through invoice/payment allocations.
Accounting period: payment date for cash-flow views.
Changed/source updated time: source changed date where available.
Raw payload retention: payment payload.
Audit expectations: sync and reconciliation decisions audited.

### AccountingPaymentAllocation

Identity: payment id plus invoice id plus amount/sequence.
Source system: Merit or bank matching.
External ID: provider allocation id if available.
Organization: required.
Project relation: through invoice/project allocation.
Accounting period: payment date.
Changed/source updated time: inherited.
Raw payload retention: allocation evidence.
Audit expectations: manual match confirmations audited.

### AccountingAccount

Identity: integration plus account code.
Source system: Merit.
External ID: account code or provider id.
Organization: required.
Project relation: none directly.
Accounting period: account mappings may have effective dates.
Changed/source updated time: source changed date.
Raw payload retention: account metadata.
Audit expectations: reporting category mappings audited.

### ProjectFinancialPeriod

Identity: organization plus project plus period start/end.
Source system: Workspace aggregate definition.
External ID: none.
Organization: required.
Project relation: required.
Accounting period: required.
Changed/source updated time: generated/recomputed time.
Raw payload retention: not raw; references source sync runs.
Audit expectations: recomputation and rule changes audited.

### ProjectFinancialSnapshot

Identity: project plus period plus generation timestamp/version.
Source system: Workspace.
External ID: none.
Organization: required.
Project relation: required.
Accounting period: required.
Changed/source updated time: generated_at.
Raw payload retention: frozen aggregate and source references.
Audit expectations: generated, approved, distributed events audited.

### FinancialAlert

Identity: organization plus alert type plus project/period/source key.
Source system: Workspace rule evaluation.
External ID: deterministic alert key.
Organization: required.
Project relation: optional or required depending on alert.
Accounting period: optional.
Changed/source updated time: evaluated_at and resolved_at.
Raw payload retention: evidence and rule version.
Audit expectations: created, dismissed, resolved, recomputed audited.

### InvoiceReconciliationMatch

Identity: source invoice/document/payment pair plus match method.
Source system: Workspace reconciliation.
External ID: deterministic match key.
Organization: required.
Project relation: optional through invoice or document.
Accounting period: optional.
Changed/source updated time: suggested_at, confirmed_at.
Raw payload retention: evidence, confidence, method.
Audit expectations: suggestions, confirmations, corrections audited.

### FinancialReport

Identity: report type plus project/recipient/period/version.
Source system: Workspace.
External ID: none unless exported to provider.
Organization: required.
Project relation: optional portfolio or required project report.
Accounting period: required for monthly reports.
Changed/source updated time: generated, approved, delivered timestamps.
Raw payload retention: frozen rendered data or snapshot references.
Audit expectations: generated, approved, sent, failed audited.

### FinancialReportRecipient

Identity: report plus recipient party/user role.
Source system: Workspace policy/configuration.
External ID: none.
Organization: required.
Project relation: optional through report.
Accounting period: inherited.
Changed/source updated time: active period and delivery timestamps.
Raw payload retention: delivery metadata only.
Audit expectations: recipient configuration and delivery audited.

### FinancialReportDelivery

Identity: report plus recipient plus delivery attempt.
Source system: Workspace.
External ID: provider message id if sent by e-mail/API.
Organization: required.
Project relation: inherited from report.
Accounting period: inherited.
Changed/source updated time: sent_at/failed_at.
Raw payload retention: delivery summary, not secrets.
Audit expectations: every delivery attempt audited.

## 6. Identity And Idempotency

Stable identities:

- GL batches: integration plus external batch ID.
- GL transaction lines: batch external ID plus line external ID, or deterministic line key.
- Sales invoices: integration plus Merit invoice GUID.
- Purchase invoices: integration plus Merit purchase invoice GUID.
- Payments: integration plus payment GUID.
- Allocations: parent source ID plus dimension ID, dimension value code, amount, and sequence where required.

Every sync must:

- upsert;
- avoid duplicates;
- retain external IDs;
- preserve provider and integration identity;
- be safe to rerun;
- preserve historical source changes and source timestamps.

Do not use invoice number alone as a primary identity. Invoice numbers are matching evidence, not globally stable identifiers.

## 7. Incremental Synchronization

Financial sync has two modes.

### Initial Backfill

Initial backfill is period-based, bounded, resumable, and observable.

Rules:

- split large history into bounded periods;
- persist progress per source;
- allow retry without duplicates;
- avoid long web requests;
- record sync run counts and safe errors.

### Incremental Sync

Incremental sync uses source changed dates where supported.

Rules:

- maintain separate cursors for GL transactions, sales invoices, purchase invoices, and payments;
- overlap query windows safely to handle provider clock or delayed updates;
- upsert changed records;
- never assume document date alone captures source modifications;
- keep source-specific failure state, because one source can fail while another remains fresh.

Do not use one shared cursor for all financial sources.

## 8. Merit API Constraints

Known architecture constraints from Merit API usage:

- GL full-detail queries use bounded date periods.
- Sales and GL list endpoints have their own maximum period limits.
- `ChangedDate` may be used where supported.
- API rate limits and errors must be handled with safe retry/recovery patterns.
- Every request uses existing Merit authentication and connector abstractions.
- Endpoint paths belong inside `MeritAPIClient`, not services, views, models, or templates.
- Automated tests must mock HTTP and never call real Merit.

Future tasks must confirm exact endpoint names and period limits against official Merit documentation before implementing API methods.

## 9. Transaction And Allocation Model

One accounting row may be allocated:

- fully to one project;
- partially across multiple projects;
- partly without project allocation;
- across project and other dimensions simultaneously.

Project reporting must use allocation amounts, not simply assign the whole invoice or GL row to every referenced project.

Definitions:

- `allocated_amount`: amount assigned to a specific project/dimension allocation.
- `unallocated_amount`: amount without project allocation.
- `allocation_percentage`: share of parent amount where derivable.
- `currency_amount`: amount in transaction currency.
- `base_currency_amount`: amount in organization/base currency.

Do not double-count rows with multiple dimensions. A line with project and department dimensions is still one financial line; reporting must separate dimensions without multiplying the value.

## 10. Account Classification

GL accounts become reporting categories through configuration.

Example categories:

- Revenue: sales revenue, other operating revenue, project-specific revenue adjustments.
- Direct costs: materials, subcontractors, equipment, transport, project-specific services.
- Labor: wages, payroll taxes, project labor allocations.
- Indirect/overhead: company overhead, administration, non-project expenses.
- Other: financial income/cost, depreciation, tax, unclassified.

Do not hardcode Estonian account numbers in business logic.

Future configuration should map:

```text
GL account/account range
-> reporting category
-> include/exclude from project result
```

Mappings need effective dates, audit, test coverage, and review before they affect management reports.

## 11. Revenue And Cost Calculation

Monthly formulas:

```text
Project revenue = sum(project-allocated revenue GL amounts)
Project cost = sum(project-allocated cost GL amounts)
Project result = revenue - cost
Margin = result / revenue, where revenue is non-zero
```

Handle:

- credit invoices;
- reversals;
- correcting entries;
- negative revenues;
- negative costs;
- currency conversions;
- reopened accounting periods.

Avoid deriving final financial result only from invoice gross totals. GL/posting data remains the booked accounting basis for project financial result.

## 12. VAT Treatment

Track separate values:

- net amount;
- VAT amount;
- gross amount.

Project profitability should normally use net accounting values unless reporting policy states otherwise.

VAT must not be counted as project revenue or project cost merely because it appears on an invoice. VAT reporting and profitability reporting are separate concerns.

## 13. Time And Period Rules

Separate dates:

- document date;
- posting date;
- invoice date;
- payment date;
- accounting period;
- changed date;
- project start/end date;
- reporting timezone.

MVP reporting period: calendar month.

Monthly financial performance should primarily use accounting/posting date policy. Invoice issuance alerts should use sales invoice document date. Cash-flow reporting should use payment date. These must remain separate views and labels.

## 14. Sales Invoice Presence Rule

Future alert: `missing_revenue_invoice`.

Possible logic for an active project and reporting month:

- project has costs or active work;
- no project-linked sales invoice exists in that month;
- project is not exempt;
- optional grace period has passed.

The rule must not assume every active project requires monthly billing.

Future per-project settings may include:

- monthly billing expected;
- milestone billing;
- no monthly invoice required;
- reporting start/end dates;
- billing contact.

## 15. Negative Month Rule

Future alert: `negative_month`.

Condition:

- monthly project result is below a configured threshold.

Variants:

- any negative result;
- result below absolute threshold;
- margin below configured percentage;
- consecutive negative months;
- costs without revenue.

Alerts should be explainable, auditable, dismissible with reason, and recomputable when source data changes.

## 16. Invoice Reconciliation

Reconciliation is three-way:

```text
E-mail / Document evidence
<-> Merit invoice record
<-> Payment / bank evidence
```

Examples:

- Email invoice exists plus Merit invoice missing -> `missing_in_merit`.
- Merit invoice exists plus no e-mail/Document source -> `source_document_missing`.
- Merit invoice exists plus payment missing after due date -> `overdue_unpaid`.
- Bank payment exists plus no matched Merit invoice -> `unmatched_payment`.
- Same supplier plus invoice number plus amount occurs twice -> `duplicate_suspected`.

Reconciliation should produce match candidates with evidence. It must not silently rewrite source data.

## 17. Matching Strategy

Deterministic matching hierarchy for purchase invoices:

1. Merit external ID already linked.
2. Supplier registration/VAT number plus invoice number.
3. Supplier plus invoice number.
4. Exact amount plus invoice date plus supplier.
5. Reference number.
6. Bank payment reference.
7. Probabilistic suggestion requiring confirmation.

Do not auto-confirm uncertain matches.

Every match should contain:

- confidence;
- evidence;
- matching method;
- confirmation status;
- confirmed_by;
- confirmed_at.

Legacy invoice/PST extraction and bank reconciliation logic remains useful as reference behavior, but future Django implementation should expose matching evidence through services and tests.

## 18. Project Financial Snapshot

`ProjectFinancialSnapshot` is a reproducible read model or frozen report state.

Suggested conceptual fields:

- project;
- period_start;
- period_end;
- currency;
- revenue;
- material_cost;
- subcontractor_cost;
- labor_cost;
- other_cost;
- total_cost;
- result;
- margin;
- sales_invoice_count;
- purchase_invoice_count;
- payment_count;
- unallocated_transaction_count;
- warning_count;
- generated_at;
- source_sync_run IDs;
- metadata.

Live aggregation and frozen snapshots are separate concepts. Live aggregation helps interactive dashboards; frozen snapshots support approved reports, audit, and reproducibility.

## 19. Financial Timeline

Project Workspace should later combine:

- invoices issued;
- supplier invoices;
- payments;
- GL postings;
- corrections;
- financial alerts;
- report generation;
- report delivery.

Financial timeline events must link back to source data. A number on a report should drill down to source lines, allocations, account mappings, sync run, and audit trail.

## 20. Report Generation

Report types:

- monthly project financial report;
- project manager portfolio report;
- management summary;
- missing revenue invoice report;
- negative project month report;
- missing source-document report;
- unpaid invoice report;
- reconciliation exception report.

Reports must use frozen snapshot data where reproducibility matters. Draft reports can be regenerated while source data is incomplete, but approved reports need stable source references.

## 21. Report Recipients

Use `ProjectParty` and organization roles where practical.

Possible recipients:

- project manager;
- site manager;
- company owner/management;
- accounting user;
- office administrator;
- customer only through explicit policy.

Recipient rules must support:

- role;
- project;
- report type;
- frequency;
- delivery method;
- active period;
- approval requirement.

Do not send reports directly to every `ProjectParty` by default. Recipients are policy/configuration decisions.

## 22. Report Approval And Delivery

Flow:

```text
Financial data sync
-> aggregation
-> alerts
-> report draft
-> review/approval where required
-> delivery
-> audit
```

Initial MVP should create report drafts and require human approval.

Future low-risk internal reports may be automatically distributed by policy. External/customer reports always require explicit permission and approved templates.

## 23. Report Formats

Future formats:

- Workspace HTML;
- PDF;
- e-mail summary;
- Excel export;
- CSV data export;
- API response.

The internal financial model must not depend on one presentation format. Rendering is a presentation concern; source data, snapshots, and audit are domain concerns.

## 24. Project Workspace Integration

Future Project Workspace Financials area:

Summary:

- current month;
- year-to-date;
- lifetime;
- revenue;
- cost;
- result;
- margin.

Tabs:

- Overview;
- Monthly;
- Revenue;
- Costs;
- Invoices;
- Payments;
- Alerts;
- Reconciliation;
- Reports;
- Audit.

Users should drill from every number to source transactions, allocations, account mappings, documents, payments, sync runs, and audit events.

## 25. Organization-Level Financial Workspace

Future views:

- all active projects;
- projects with negative month;
- projects without revenue invoices;
- highest revenue;
- lowest margin;
- unallocated accounting transactions;
- missing documents;
- overdue unpaid invoices;
- sync health.

Organization-level views require stronger permissions than normal project views because they may expose company-wide margins, salaries, overhead, and supplier costs.

## 26. Security And Permissions

Financial data requires stronger permissions than general project data.

Possible roles:

- `financial_admin`;
- `management`;
- `accountant`;
- `project_manager`;
- `project_viewer`.

Rules:

- Project managers may see only permitted projects.
- Supplier costs, payroll/labor costs, and company-wide margins may require separate visibility controls.
- External reports require explicit permission and approval.
- No API secrets or raw authentication details may appear in reports or audit metadata.
- Financial exports should be audited and permission-controlled.

## 27. Audit And Explainability

Audit events:

- sync started/completed/failed;
- mappings changed;
- manual invoice match confirmed;
- alert dismissed;
- report generated;
- report approved;
- report sent;
- project financial settings changed.

Every aggregate must be explainable through:

- source transactions;
- allocations;
- account mappings;
- period rules;
- sync runs.

Explainability is not optional for financial reporting. Users must be able to understand why a project shows a result, margin, warning, or missing invoice alert.

## 28. Error Handling And Data Quality

Quality states:

- complete;
- partial;
- stale;
- sync_failed;
- unallocated;
- unmapped_account;
- conflict;
- awaiting_confirmation.

A report must clearly show if:

- latest sync failed;
- source period is incomplete;
- transactions lack project allocation;
- account mapping is incomplete;
- invoices/payments are not fully reconciled.

Never show uncertain financial totals as fully reliable without warning.

## 29. Performance And Storage

Support:

- many years of transactions;
- thousands of invoices;
- monthly incremental sync;
- organization isolation;
- project and period indexes;
- PostgreSQL production deployment.

Do not repeatedly calculate all historical data from raw JSON on every page request.

Use:

- normalized local cache;
- indexed allocations;
- aggregated snapshots/read models;
- bounded sync periods.

Raw payloads are retained for traceability, but UI truth should come from normalized, validated cache/read models.

## 30. Background Jobs

Future jobs:

- GL sync;
- sales invoice sync;
- purchase invoice sync;
- payment sync;
- invoice detail enrichment;
- reconciliation;
- monthly aggregation;
- alert evaluation;
- report generation;
- report delivery.

Web requests should not remain open during large historical syncs. Manual UI actions may enqueue jobs or run very small checks, but full financial backfills need observable background execution.

## 31. MVP Implementation Path

Proposed sequence:

1. `FIN-001` Merit GL Full Details API Method
2. `FIN-002` Accounting Sync Cursor and Run Model
3. `FIN-003` General Ledger Transaction Cache
4. `FIN-004` GL Transaction Sync Service
5. `FIN-005` Merit Sales Invoice API Methods
6. `FIN-006` Merit Purchase Invoice API Methods
7. `FIN-007` Merit Payment API Methods
8. `FIN-008` Accounting Invoice and Payment Cache
9. `FIN-009` Invoice and Payment Sync Services
10. `FIN-010` Account Classification Settings
11. `FIN-011` Monthly Project Financial Aggregator
12. `FIN-012` Financial Alert Rules
13. `FIN-013` Invoice Document Reconciliation Architecture/Service
14. `MVP-FIN-001` Project Financial Overview UI
15. `MVP-FIN-002` Financial Alerts and Review UI
16. `MVP-FIN-003` Invoice Reconciliation UI
17. `MVP-FIN-004` Financial Report Draft and Approval UI
18. `MVP-FIN-005` Report Distribution

Each task must remain small, tested, and committed separately.

## 32. Non-Goals

Do not implement now:

- replacing Merit;
- editing Merit GL entries;
- automatic accounting decisions;
- payroll integration;
- tax declarations;
- full budgeting;
- cash-flow forecasting;
- customer invoicing workflow;
- automatic external report sending;
- direct bank integration;
- OCR;
- accounting write-back;
- universal ERP.

## 33. Engineering Rules

Rules:

- Merit remains accounting system of record.
- GL, invoices, and payments are separate source identities.
- Sync is incremental, idempotent, and auditable.
- Project totals use allocation amounts.
- Never double-count multi-dimensional allocations.
- Financial reports must drill down to source records.
- Document evidence and accounting records remain separate but linkable.
- Uncertain invoice matches require user confirmation.
- External report sending is policy-controlled and audited.
- Views remain thin; services aggregate and decide.
- Connectors own endpoint knowledge.
- Financial calculations must be deterministic and testable.
- No raw financial API payload is used directly as UI truth.
- Reopened or changed periods must be resyncable and recomputable.
- API secrets, signatures, and credentials must never appear in report data, audit payloads, or logs.
