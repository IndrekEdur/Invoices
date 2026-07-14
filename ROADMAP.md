# Roadmap

This roadmap describes the intended direction for the invoice automation project. It is not a commitment to implement all items immediately.

`MASTER_ARCHITECTURE.md` is the main architecture reference for aligning roadmap tasks with the broader AI Business Operating System vision.

Current architecture phase: Financial Alert Architecture.

Current product phase: Operations Workspace MVP.

Current engineering phase: Engineering Standards.

Current implementation phase: Platform Core.

Current implementation: Allocation Wizard and Live Preview.

Planned financial follow-ups: FIN-ALERT-001 Alert Models and Detection Engine, MVP-FIN-004 Financial Alerts List and Project UI, FIN-ALERT-002 Scheduled Evaluation, FIN-ALERT-003 Weekly Alert Email Digest, saved allocation templates, source freshness warnings, scheduled monthly proposal creation, multi-month historical GL backfill UI, background financial sync execution, scheduled GL synchronization, sync progress UI, COST-ALLOC-005 Allocation Revision/Audit Enhancements, management allocation reporting, financial report drafts, scheduled report distribution, and invoice/payment reconciliation.

Planned follow-up: MERIT-014 should define explicit Merit dimension close/reopen behavior after Workspace project completion or archival. Current status changes are local, audited Workspace actions only.

Current implementation focus: End-to-End Email Processing.

## Phase 0: Preserve the Working Prototype

- Keep the current local Python application working.
- Keep SQLite data and real invoice/bank files out of Git.
- Maintain `SPECIFICATION.md` and `ARCHITECTURE_REVIEW.md` as product and architecture references.
- Add repository hygiene files, test configuration, and contribution notes.

## Phase 1: Stabilize the Legacy Codebase

- Keep current behavior unchanged.
- Add focused tests around extraction, matching, Merit payloads, and bank import.
- Move risky business rules into documented, testable service functions only when necessary.
- Avoid large refactors until the target architecture is ready.

## Phase 2: Start the Target Django Stack

- Add a Django project beside the current application. Initial skeleton exists in `platform/`.
- Current foundation step: build the Platform Core tenant model, starting with Organization, before expanding documents, workflow, policy, knowledge, and accounting around it.
- Use PostgreSQL as the target database.
- Use HTMX for server-rendered interactive workflows.
- Add initial models for invoices, documents, bank transactions, imports, Merit operations, and reconciliation runs.
- Add a one-way legacy SQLite import command.

## Phase 3: Migrate Workflows Incrementally

Recommended order:

1. Invoice list and invoice detail review.
2. Manual invoice upload.
3. Bank statement import.
4. Bank-to-invoice reconciliation with persisted match results.
5. Read-only Merit sync.
6. Bank vs Merit view.
7. Merit invoice send.
8. Merit payment send.
9. Project/dimension sync.
10. EMTA export preview and export.

## Phase 4: Retire the Local Prototype UI

- Keep reusable parsing/scoring modules.
- Keep the old app as a reference until Django covers daily work.
- Freeze the legacy web UI once replacement workflows are stable.

## Guiding Principles

- Do not lose working business logic.
- Prefer small, auditable steps.
- Keep external API writes explicit and logged.
- Treat matching scores as evidence, not absolute truth.
- Keep user confirmation in all tax/accounting-critical workflows.
