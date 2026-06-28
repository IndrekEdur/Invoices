# Master Architecture

This document is the central long-term architecture reference for the project. More specific documents can expand on individual areas, but product direction, domain boundaries, and engineering rules should align with this file.

## 1. Vision

The product is an AI Business Operating System: a practical internal platform that helps a company receive information, understand it, route it through review workflows, learn from corrections, and execute approved business actions.

Accounting and invoice automation is the first real module because it has immediate value and clear data flows: documents, invoices, suppliers, bank transactions, Merit, and EMTA. It is not the whole product. The platform must later support wider business workflows such as quotations, projects, procurement, BIM/IFC tooling, CRM, fleet management, inventory, reporting, and business intelligence.

The goal is not to replace human responsibility. The goal is to reduce repetitive work, make decisions traceable, and help the company build reusable operational knowledge.

## 2. Product Principles

- Human-in-the-loop by default.
- AI can suggest, classify, extract, and match, but high-risk changes need confirmation.
- Every important decision must be traceable to input data, user action, AI reasoning, API response, or business rule.
- Learning happens from confirmed corrections, not from unverified guesses.
- External system writes must be explicit, previewed, logged, and reversible where possible.
- The system should explain why it proposed a match, status, account, project, VAT treatment, or workflow action.

## 3. Platform Layers

### Core

Core contains shared technical foundations: settings, company context, user profiles, permissions, time handling, shared identifiers, and common UI conventions.

### Documents

Documents are the root layer for all imported and generated files. A file enters the system as a document before it becomes an invoice, bank statement, Merit import, EMTA export, project file, or any other domain-specific object.

### Workflow

Workflow stores event-driven process state. It records what happened, who or what caused it, what needs review, and which step should happen next.

### Policy Layer

The Policy Layer decides what actions are allowed based on company rules, risk, confidence, permissions, thresholds, trust, history, and compliance rules.

### Cognitive Layer

The Cognitive Layer performs OCR, extraction, validation, confidence scoring, decision support, review routing, learning, knowledge retrieval, business reasoning, prompt execution, and AI job logging. It includes AI/LLM capabilities, but it is not limited to AI.

### Learning Engine

The Learning Engine turns confirmed corrections into reusable rules, aliases, layout patterns, and business preferences.

### Knowledge Engine

The Knowledge Engine stores company knowledge, not only raw data. It should preserve recurring patterns, approved exceptions, supplier-specific behavior, project allocation rules, and account selection logic.

### Integrations

Integrations handle external systems such as Outlook, Microsoft 365, Merit Aktiva, banks, EMTA, SharePoint, OneDrive, Google Drive, and future REST APIs.

### Accounting

Accounting contains purchase invoices, sales invoices, invoice lines, VAT handling, payment status, bank matching, Merit sync, and EMTA export previews.

### Future Business Modules

Future modules can use the same document, workflow, AI, learning, knowledge, and integration foundations for quotations, projects, BIM/IFC, procurement, inventory, CRM, fleet management, and business intelligence.

The platform should be policy-driven, event-driven, knowledge-aware, and capability-based.

### Platform Layering Diagram

```text
Business Modules
  -> Business Processes
  -> Policy Layer
  -> Workflow Layer
  -> Event Layer
  -> Cognitive Layer
  -> Knowledge Layer
  -> Platform Core
  -> Storage
```

## 4. Domain Model Overview

Invoice is not the root object. Document and Event are the platform roots.

Documents represent source material and generated artifacts. Events represent what happened to those documents and to the business objects derived from them. Invoices, bank transactions, supplier matches, payment matches, and accounting exports are downstream interpretations.

### Relationship Map

```text
Document -> Invoice -> InvoiceLine
Document -> WorkflowEvent
Document -> ProcessingJob -> AIJob -> ExtractionResult
Invoice -> Supplier
Invoice -> PaymentMatch -> BankTransaction
BankStatement -> BankTransaction
UserCorrection -> LearningRule -> KnowledgeFact
SupplierAlias -> Supplier
IntegrationSyncRun -> ExternalObjectMapping
ReviewTask -> UserDecision -> WorkflowEvent
```

### A. Core Domain

#### Company

Purpose: tenant and business context for all operational data.

Key fields: legal name, registry code, VAT number, default currency, country, active flag, created/updated timestamps.

Relationships: owns documents, invoices, suppliers, bank statements, integration accounts, users, workflow events, audit events, learning rules, and knowledge facts.

Lifecycle: created during setup, configured with company metadata, used as the root data boundary, archived only when the company is no longer active.

Future notes: multi-company support must be designed around Company from the beginning so accounting and banking data never leak between companies.

#### User/Profile

Purpose: represents a human actor and their workflow preferences.

Key fields: user account, display name, e-mail, active company, language, notification settings, approval limits, created/updated timestamps.

Relationships: belongs to one or more companies through roles, creates user corrections, decisions, approvals, audit events, and review task actions.

Lifecycle: invited, activated, assigned roles, used in workflows, deactivated when access should end.

Future notes: profile-level preferences can tune review queues, default filters, and notification routing without changing company-wide rules.

#### Role/Permission

Purpose: controls what a user can view, correct, approve, export, or send to external systems.

Key fields: role name, permission code, scope, company, active flag.

Relationships: assigned to users/profiles, checked by workflow actions, admin pages, integration writes, EMTA exports, and payment operations.

Lifecycle: created from default role templates, adjusted per company, reviewed periodically, retired when no longer used.

Future notes: high-risk actions need explicit permissions, especially Merit writes, bank payment preparation, EMTA export approval, and learning rule activation.

#### AuditEvent

Purpose: durable trace of important business and system decisions.

Key fields: actor, company, event type, target object type/id, before/after values, reason, source, timestamp, request id.

Relationships: linked to users, companies, documents, invoices, payments, integrations, AI jobs, and workflow events.

Lifecycle: created automatically when important actions occur, retained long term, queried for investigation and compliance.

Future notes: audit events should be append-only; correction should happen by adding a new event, not editing old history.

### B. Document Domain

#### Document

Purpose: root record for every imported or generated file.

Key fields: uuid, title, original filename, source, status, file path, sha256, MIME type, size, metadata, created/updated timestamps.

Relationships: has versions, tags, relationships, workflow events, processing jobs, extraction results, invoices, bank statements, imports, and exports.

Lifecycle: received or generated, stored, fingerprinted, parsed, reviewed, approved, archived, or marked as error.

Future notes: all file-based modules should start here instead of creating separate file identity fields.

#### DocumentVersion

Purpose: captures replaced, transformed, repaired, OCR-enhanced, or regenerated document files.

Key fields: document, version number, file path, sha256, MIME type, size, note, created timestamp.

Relationships: belongs to a document; may be referenced by extraction results, AI jobs, and audit events.

Lifecycle: created when a document file changes or an alternative derived file is produced; retained for traceability.

Future notes: versioning allows the system to answer which exact file was parsed or sent to an external system.

#### DocumentTag

Purpose: lightweight classification of documents.

Key fields: document, name, created timestamp.

Relationships: belongs to a document; can be added by users, AI, imports, or workflow rules.

Lifecycle: added during intake or review, used in filtering and routing, removed or superseded when wrong.

Future notes: tags are flexible hints, not authoritative accounting classification.

#### DocumentRelationship

Purpose: describes relationships between documents.

Key fields: source document, target document, relationship type, confidence, note, created timestamp.

Relationships: connects documents such as invoice and credit invoice, e-mail body and attachment, original PDF and OCR text, bank import and generated report.

Lifecycle: created during import, parsing, matching, or manual review; corrected if the relationship was wrong.

Future notes: relationship types should remain explicit: derived_from, replaces, duplicate_of, supports, exported_as, attached_to.

### C. Workflow/Event Domain

#### WorkflowEvent

Purpose: records a meaningful process event for a document or domain object.

Key fields: company, event type, target object, actor, payload, status, created timestamp.

Relationships: links documents, invoices, users, processing jobs, review tasks, learning rules, and audit events.

Lifecycle: appended whenever a workflow step occurs; never silently overwritten.

Future notes: workflow event streams should power timelines, progress screens, and process diagnostics.

#### DomainEvent

Purpose: technical event abstraction for cross-module communication.

Key fields: event name, aggregate type/id, payload, correlation id, causation id, created timestamp, processed flag.

Relationships: emitted by domain services and consumed by workflow, learning, notification, integration, or reporting handlers.

Lifecycle: emitted after business state changes, processed by handlers, stored for retry and observability.

Future notes: domain events should be introduced carefully so simple Django flows do not become over-engineered too early.

#### ProcessingJob

Purpose: tracks long-running or asynchronous work.

Key fields: job type, status, input document/object, current step, progress count, total count, result, error, started/finished timestamps.

Relationships: can own AI jobs, extraction results, workflow events, and notifications.

Lifecycle: queued, running, completed, failed, retried, or cancelled.

Future notes: jobs should expose live progress and structured logs for imports, OCR, matching, Merit sync, and EMTA export preparation.

#### StatusTransition

Purpose: records explicit state movement for important objects.

Key fields: object type/id, from status, to status, actor, reason, created timestamp.

Relationships: linked to documents, invoices, payments, review tasks, workflow events, and audit events.

Lifecycle: created when status changes; used to explain why an object moved from one state to another.

Future notes: status transitions should prevent invisible state changes in high-risk accounting workflows.

### D. Accounting Domain

#### Supplier

Purpose: known supplier or business partner.

Key fields: name, registry code, VAT number, IBANs, e-mail domains, address, active flag, metadata.

Relationships: has aliases, invoices, payments, learning rules, and external mappings.

Lifecycle: created from Merit sync, invoice extraction, or user review; merged when duplicates are found; archived when no longer active.

Future notes: supplier identity should be evidence-based and support fuzzy matching without hiding uncertainty.

#### SupplierAlias

Purpose: alternative names and identifiers that help match documents to suppliers.

Key fields: supplier, alias type, value, confidence, source, active flag, created timestamp.

Relationships: belongs to supplier; derived from documents, corrections, Merit data, bank transactions, and learning rules.

Lifecycle: proposed by AI or matching, confirmed by user or high-confidence sync, used in future matching.

Future notes: aliases should preserve provenance so bad aliases can be traced and disabled.

#### Invoice

Purpose: accounting interpretation of a document as a purchase or sales invoice.

Key fields: document, invoice type, supplier/customer, invoice number, issue date, due date, currency, net amount, VAT amount, gross amount, status, external ids.

Relationships: references document, supplier, invoice lines, payment matches, workflow events, Merit mappings, and audit events.

Lifecycle: drafted from extraction, reviewed, approved, sent/synced, paid/matched, archived, or rejected.

Future notes: invoice is not the root; it is a derived business object backed by document and event history.

#### InvoiceLine

Purpose: row-level invoice detail for accounting, VAT, project allocation, and reporting.

Key fields: invoice, description, quantity, unit price, net amount, VAT rate, VAT amount, account, project/dimension, cost category, row order.

Relationships: belongs to invoice; may reference project, dimension values, VAT treatment, AI extraction result, and user corrections.

Lifecycle: extracted, reviewed, corrected, approved, exported to Merit or reporting.

Future notes: line-level project and account allocation is essential for later project profitability and business intelligence.

#### VATTreatment

Purpose: describes VAT logic and validation for invoices and invoice lines.

Key fields: VAT rate, VAT code, country, reverse charge flag, taxable flag, explanation, effective dates.

Relationships: used by invoice lines, invoices, EMTA export previews, and validation results.

Lifecycle: configured from accounting rules, applied during validation, updated when tax rules change.

Future notes: VAT rules are high-risk and should remain explicit, tested, and reviewable.

#### Payment

Purpose: represents payment state and payment action for invoices.

Key fields: invoice, amount, currency, payment date, status, method, external id, note.

Relationships: linked to invoice, bank transactions, payment matches, Merit sync, and audit events.

Lifecycle: proposed from bank match, confirmed, sent to Merit, reconciled, corrected if wrong.

Future notes: payment should distinguish actual bank movement from accounting-system status.

#### BankStatement

Purpose: imported bank statement file and statement-level metadata.

Key fields: document, bank, account IBAN, period start/end, currency, import hash, created timestamp.

Relationships: references document and has many bank transactions.

Lifecycle: imported from XML/CSV/API, parsed, deduplicated, used for matching, archived.

Future notes: statement imports must be idempotent so repeated imports add only new transactions.

#### BankTransaction

Purpose: individual bank account movement.

Key fields: statement, booking date, value date, amount, currency, counterparty name, counterparty IBAN, reference, explanation, bank transaction id.

Relationships: belongs to bank statement; can match invoices through payment matches.

Lifecycle: imported, deduplicated, matched, reviewed, linked to payments, ignored, or classified.

Future notes: bank data should preserve raw fields from the bank for auditability.

#### PaymentMatch

Purpose: evidence record connecting invoices and bank transactions.

Key fields: invoice, bank transaction, score, reasons, amount matched, status, confirmed by, confirmed timestamp.

Relationships: links invoice, bank transaction, payment, AI job, validation result, and audit event.

Lifecycle: proposed by matching logic, reviewed, accepted/rejected, used to update payment status.

Future notes: match reasons are as important as score because users need to understand the proposed link.

### E. Project/Dimension Domain

#### Project

Purpose: company project, object, or job used for allocation and profitability.

Key fields: code, name, status, year, customer, start/end dates, external id, metadata.

Relationships: referenced by invoice lines, dimensions, Merit mappings, learning rules, and reports.

Lifecycle: imported or created, active during work, closed, archived, used in historical reporting.

Future notes: project codes may be detected from invoice text and later mapped to Merit dimensions.

#### Dimension

Purpose: named allocation axis such as project, cost center, object, department, or activity.

Key fields: name, code, source system, active flag, created timestamp.

Relationships: contains dimension values and is used by invoice lines, reporting, and integrations.

Lifecycle: configured, synced with external systems, used in allocations, retired when no longer active.

Future notes: dimensions must stay flexible because Merit and internal reporting may model allocations differently.

#### DimensionValue

Purpose: selectable value under a dimension.

Key fields: dimension, code, name, active flag, external id, metadata.

Relationships: assigned to invoice lines, projects, cost categories, and external mappings.

Lifecycle: imported or created, used in accounting records, synced, archived.

Future notes: many project-like allocations can be represented as dimension values.

#### CostCategory

Purpose: internal classification for costs and reporting.

Key fields: code, name, default account, default VAT treatment, active flag.

Relationships: used by invoice lines, learning rules, account assignment memory, and reporting.

Lifecycle: configured by accounting/business rules, suggested by AI, confirmed by users.

Future notes: cost categories should bridge operational language and accounting accounts.

### F. AI Domain

#### AIJob

Purpose: logged execution of AI/OCR/parsing/matching work.

Key fields: job type, provider, model, prompt template, input references, output payload, confidence, status, error, timestamps.

Relationships: linked to documents, processing jobs, extraction results, validation results, and workflow events.

Lifecycle: queued, executed, completed, reviewed, accepted, corrected, or failed.

Future notes: AI jobs should be reproducible enough to explain outputs even if exact model behavior changes later.

#### PromptTemplate

Purpose: versioned instruction template for AI tasks.

Key fields: name, version, task type, template text, schema, active flag, created timestamp.

Relationships: used by AI jobs and associated with extraction/validation outputs.

Lifecycle: drafted, tested, activated, superseded, archived.

Future notes: prompt versioning is required for traceability and regression testing.

#### ExtractionResult

Purpose: structured result extracted from a document or document version.

Key fields: document, document version, extraction type, payload, confidence, raw text reference, created timestamp.

Relationships: produced by processing jobs or AI jobs; used to create invoices, bank statements, supplier aliases, and validation results.

Lifecycle: produced, reviewed, corrected, accepted, superseded by a better extraction.

Future notes: keep raw extraction separate from approved business objects.

#### ConfidenceScore

Purpose: normalized confidence and explanation for AI or matching outputs.

Key fields: target object, score, reasons, evidence fields, model/rule source, created timestamp.

Relationships: attached to extraction results, supplier matches, payment matches, project detection, and validation results.

Lifecycle: generated with a proposed result, displayed in review, retained after decision.

Future notes: confidence alone is insufficient; reasons and evidence must be stored.

#### ValidationResult

Purpose: records rule or AI validation outcome.

Key fields: target object, validation type, status, severity, message, payload, created timestamp.

Relationships: linked to invoices, invoice lines, VAT treatment, payment matches, AI jobs, and review tasks.

Lifecycle: generated during parsing or review, resolved by correction or acceptance, retained as evidence.

Future notes: validations should separate blocking errors from warnings and informational hints.

### G. Learning Domain

#### UserCorrection

Purpose: captures a user correction to AI, parsing, matching, or classification.

Key fields: user, target object, field name, old value, new value, reason, created timestamp.

Relationships: can generate learning rules, knowledge facts, supplier aliases, and audit events.

Lifecycle: created during review, evaluated for repeatability, converted into a learning rule if useful.

Future notes: corrections are high-value training data and should never be discarded casually.

#### LearningRule

Purpose: reusable rule learned from confirmed behavior.

Key fields: rule type, condition, action, confidence, source evidence, active flag, created/updated timestamps.

Relationships: derived from user corrections, pattern matches, supplier memory, account assignment memory, and knowledge facts.

Lifecycle: proposed, reviewed, activated, used, monitored, disabled if harmful.

Future notes: rules should explain what evidence created them and when they last helped.

#### PatternMatch

Purpose: detected repeatable pattern in documents, invoices, transactions, or user actions.

Key fields: pattern type, input signature, matched object, score, evidence, created timestamp.

Relationships: linked to learning rules, AI jobs, extraction results, and knowledge facts.

Lifecycle: detected automatically, reviewed or used as evidence, promoted into a learning rule.

Future notes: layout fingerprints and supplier invoice formats belong here.

#### SupplierMemory

Purpose: learned supplier-specific behavior.

Key fields: supplier, known IBANs, e-mail domains, invoice number patterns, default VAT/account/project hints, evidence count.

Relationships: linked to supplier, supplier aliases, learning rules, invoices, and corrections.

Lifecycle: built from confirmed invoices and corrections, updated over time, disabled or corrected when wrong.

Future notes: supplier memory should improve matching without pretending uncertain data is certain.

#### AccountAssignmentMemory

Purpose: learned account/category allocation behavior.

Key fields: supplier, description pattern, cost category, account, VAT treatment, project/dimension hints, evidence count.

Relationships: linked to invoice lines, cost categories, learning rules, user corrections, and knowledge facts.

Lifecycle: proposed from repeated corrections, activated after review, applied as a suggestion in future invoices.

Future notes: line-level memories are important for recurring suppliers with mixed invoice rows.

### H. Knowledge Domain

#### KnowledgeFact

Purpose: structured company knowledge that can support future decisions.

Key fields: subject, predicate, object, confidence, source, active flag, created/updated timestamps.

Relationships: derived from learning rules, corrections, integrations, documents, and user decisions.

Lifecycle: created from confirmed evidence, used by matching and AI prompts, reviewed or retired when outdated.

Future notes: knowledge facts should be queryable and explainable, not hidden inside prompts.

#### KnowledgeRelation

Purpose: connects knowledge facts into a usable graph.

Key fields: source fact, target fact, relation type, confidence, created timestamp.

Relationships: links facts about suppliers, projects, accounts, recurring behavior, and exceptions.

Lifecycle: created by learning or manual curation, used in reasoning, reviewed when contradictions appear.

Future notes: this can later support richer business intelligence and AI context retrieval.

#### KnowledgeSource

Purpose: provenance record for knowledge.

Key fields: source type, source object, description, trust level, created timestamp.

Relationships: referenced by knowledge facts, learning rules, and business memory entries.

Lifecycle: created when knowledge is imported or learned, used to explain why the system believes something.

Future notes: sources allow old, low-trust, or superseded knowledge to be filtered out.

#### BusinessMemoryEntry

Purpose: human-readable memory of company-specific behavior.

Key fields: title, text, category, scope, source, active flag, created/updated timestamps.

Relationships: linked to knowledge facts, learning rules, suppliers, projects, and users.

Lifecycle: written by users or generated from confirmed patterns, reviewed, used by AI/context, archived.

Future notes: business memory can make the system feel like it remembers how the company actually works.

### I. Integration Domain

#### IntegrationAccount

Purpose: configured external system connection.

Key fields: company, provider, display name, credentials reference, status, scopes, last sync timestamp, metadata.

Relationships: owns sync runs, external object mappings, webhook events, and audit events.

Lifecycle: configured, authenticated, used for read/write sync, paused, reauthorized, disabled.

Future notes: credentials should be stored securely and never committed to source control.

#### IntegrationSyncRun

Purpose: records one synchronization/import/export run.

Key fields: integration account, sync type, status, started/finished timestamps, item counts, error summary, payload metadata.

Relationships: creates documents, external mappings, workflow events, audit events, and notifications.

Lifecycle: queued, running, completed, failed, partially completed, retried.

Future notes: sync runs need progress and item-level logs for debugging large imports.

#### ExternalObjectMapping

Purpose: maps internal objects to external system identifiers.

Key fields: provider, external object type, external id, internal object type/id, sync status, last seen timestamp.

Relationships: links suppliers, invoices, payments, projects, dimensions, documents, and integration accounts.

Lifecycle: created during sync or write, updated on future syncs, marked stale if external object disappears.

Future notes: this prevents duplicate creates in Merit and other external systems.

#### WebhookEvent

Purpose: stores incoming external notifications.

Key fields: integration account, event type, payload, received timestamp, processed timestamp, status, error.

Relationships: may trigger sync runs, workflow events, notifications, or domain events.

Lifecycle: received, validated, processed, retried, archived or marked failed.

Future notes: webhooks should be idempotent and signed/verified where the provider supports it.

### J. Notification/Review Domain

#### ReviewTask

Purpose: user-facing task requiring review, correction, approval, or rejection.

Key fields: company, assigned user/role, task type, target object, priority, due date, status, created/resolved timestamps.

Relationships: linked to documents, invoices, validation results, AI jobs, workflow events, and user decisions.

Lifecycle: created by workflow or validation, assigned, opened, resolved, escalated, cancelled, or archived.

Future notes: review tasks are the operational inbox of the human-in-the-loop product.

#### Notification

Purpose: message shown or sent to a user.

Key fields: recipient, channel, title, body, severity, target object, read timestamp, created timestamp.

Relationships: can point to review tasks, workflow events, integrations, errors, or approvals.

Lifecycle: created, delivered, read, dismissed, expired.

Future notes: notifications should avoid noise by grouping low-risk events and highlighting only actionable items.

#### UserDecision

Purpose: explicit user decision on a proposed action.

Key fields: user, decision type, target object, selected option, comment, created timestamp.

Relationships: resolves review tasks, creates workflow events, audit events, user corrections, and learning evidence.

Lifecycle: requested, submitted, applied by workflow, retained for audit and learning.

Future notes: user decisions are the bridge between AI suggestions and business responsibility.

## 5. Event Model

The platform is event-driven. Important changes are recorded as events so the system can explain what happened, learn from confirmed actions, debug long-running processing, automate later steps, and provide future AI agents with trustworthy operational memory.

Events are append-only. If a decision is corrected, the platform records a new event instead of rewriting the old one. This preserves history and keeps audit, learning, and debugging reliable.

Events support:

- audit trails for accounting and integration actions;
- learning from user corrections and confirmations;
- debugging imports, parsing, matching, and external sync;
- automation triggers for review tasks, notifications, and follow-up processing;
- future AI agents that need context about prior decisions and outcomes.

### Event Categories

#### Document Events

Purpose: record the lifecycle of source files and generated artifacts.

Typical payload: document id, source, filename, checksum, MIME type, size, parsing status, error details.

Producer: document upload/import services, e-mail import, bank import, EMTA/Merit export generators, parsing jobs.

Consumers: workflow engine, Cognitive Layer, review queues, audit log, knowledge engine, downstream accounting/banking modules.

Retention/audit importance: high. Documents are evidence for later invoices, bank statements, exports, and user decisions.

Concrete examples:

- `DocumentReceived`
- `DocumentStored`
- `DocumentParsed`
- `DocumentFailedParsing`

#### Workflow Events

Purpose: record process transitions, review state, and operational routing.

Typical payload: target object type/id, previous status, new status, assigned user/role, reason, due date, review task id.

Producer: workflow services, review UI, validators, import jobs, integration callbacks.

Consumers: review inbox, notifications, audit log, progress views, dashboards, automation rules.

Retention/audit importance: high. Workflow history explains why something is waiting, approved, rejected, blocked, or archived.

Concrete examples:

- `ReviewTaskCreated`
- `ReviewTaskResolved`
- `InvoiceCandidateCreated`
- `InvoiceApproved`
- `InvoiceRejected`

#### AI Events

Purpose: record AI/OCR/parsing/matching activity and changes in confidence.

Typical payload: AI job id, model/provider, prompt template version, input document/version, output reference, confidence, reasons, errors.

Producer: Cognitive Layer, OCR jobs, extraction services, matching services, validation services.

Consumers: review UI, learning engine, audit log, knowledge engine, validation reporting.

Retention/audit importance: high. AI output must be traceable because users and later agents need to know why a suggestion was made.

Concrete examples:

- `SupplierDetected`
- `ConfidenceChanged`
- `DocumentParsed`
- `DocumentFailedParsing`

#### Learning Events

Purpose: record confirmed corrections and creation or use of learning rules.

Typical payload: correction id, target object, field corrected, old value, new value, user id, rule id, evidence count.

Producer: review UI, learning engine, user correction services, rule activation services.

Consumers: learning engine, knowledge engine, AI prompt context builder, audit log, future automation.

Retention/audit importance: high. Learning must be based on confirmed evidence and must remain explainable.

Concrete examples:

- `UserCorrectionCreated`
- `SupplierCorrected`
- `LearningRuleCreated`

#### Accounting Events

Purpose: record invoice and accounting-relevant lifecycle changes.

Typical payload: invoice id, supplier id, document id, amount, VAT summary, status, external ids, validation summary.

Producer: invoice extraction/review services, accounting services, Merit integration, EMTA export preview services.

Consumers: audit log, Merit sync, EMTA preview, payment matching, reporting, notifications.

Retention/audit importance: very high. Accounting events explain financial state and external system writes.

Concrete examples:

- `InvoiceCandidateCreated`
- `InvoiceApproved`
- `InvoiceRejected`
- `InvoiceSentToMerit`

#### Bank/Payment Events

Purpose: record bank imports, transaction matching, and payment status changes.

Typical payload: bank statement id, bank transaction id, invoice id, amount, currency, match score, match reasons, payment date.

Producer: bank import services, reconciliation services, payment services, Merit payment sync.

Consumers: accounting module, review tasks, audit log, reporting, Merit integration, notifications.

Retention/audit importance: very high. Payment matching can affect accounting status and must be explainable.

Concrete examples:

- `BankStatementImported`
- `BankTransactionMatched`
- `PaymentMatched`
- `PaymentSentToMerit`

#### Integration Events

Purpose: record external synchronization and API interactions.

Typical payload: integration account id, provider, sync run id, object type, external id, item counts, request/response summary, error details.

Producer: integration sync services, webhook handlers, external API clients.

Consumers: audit log, workflow engine, notifications, external object mapping, retry logic, dashboards.

Retention/audit importance: high. External writes and sync failures must be diagnosable.

Concrete examples:

- `IntegrationSyncStarted`
- `IntegrationSyncCompleted`
- `IntegrationSyncFailed`
- `InvoiceSentToMerit`
- `PaymentSentToMerit`

#### User/Review Events

Purpose: record human review, correction, approval, rejection, and explicit decisions.

Typical payload: user id, review task id, target object, decision type, old value, new value, comment, timestamp.

Producer: review UI, admin actions, approval screens, correction forms.

Consumers: audit log, learning engine, workflow engine, notifications, knowledge engine.

Retention/audit importance: very high. User decisions establish business responsibility and learning evidence.

Concrete examples:

- `UserCorrectionCreated`
- `SupplierCorrected`
- `ReviewTaskResolved`
- `InvoiceApproved`
- `InvoiceRejected`

#### Knowledge Events

Purpose: record creation, update, supersession, or retirement of company knowledge.

Typical payload: knowledge fact id, source id, subject, predicate, object, confidence, source evidence, active flag.

Producer: learning engine, knowledge curation UI, AI-assisted rule generation, integration imports.

Consumers: Cognitive Layer, learning engine, matching services, reporting, future AI agents.

Retention/audit importance: medium to high. Knowledge affects future suggestions and automation, so provenance matters.

Concrete examples:

- `KnowledgeFactCreated`
- `LearningRuleCreated`
- `ConfidenceChanged`

### Event Payload Example

```json
{
  "event_type": "SupplierCorrected",
  "event_id": "evt_2026_000001",
  "company_id": 1,
  "occurred_at": "2026-06-27T12:30:00Z",
  "actor": {
    "type": "user",
    "id": 42
  },
  "target": {
    "type": "Invoice",
    "id": 987
  },
  "causation_id": "evt_2026_000000",
  "correlation_id": "corr_document_123",
  "payload": {
    "document_id": 123,
    "field": "supplier",
    "old_value": "ERLIN OÜ",
    "new_value": "Esvika Elekter AS",
    "confidence_before": 0.54,
    "reason": "User corrected supplier after PDF review"
  }
}
```

The exact schema can evolve, but every event should preserve event type, actor, target, time, correlation, causation, and payload.

### Event Flow Example

```text
Email attachment received
-> DocumentReceived
-> DocumentStored
-> DocumentParsed
-> SupplierDetected
-> InvoiceCandidateCreated
-> ReviewTaskCreated
-> UserCorrectionCreated
-> SupplierCorrected
-> LearningRuleCreated
-> InvoiceApproved
-> InvoiceSentToMerit
-> PaymentMatched
```

This flow shows how the system moves from raw input to accounting action without losing traceability. Each step can be inspected, retried, corrected, or used as learning evidence.

### WorkflowEvent vs DomainEvent vs AuditEvent

`WorkflowEvent` records process movement: review tasks, status changes, assignments, approvals, rejections, and operational state. It answers "where is this item in the process?"

`DomainEvent` records that a meaningful business fact happened inside the domain. It can trigger handlers and automation. It answers "what business thing happened?"

`AuditEvent` records durable accountability for important actions, especially high-risk or externally visible actions. It answers "who or what changed this, when, from what, to what, and why?"

These may refer to the same underlying action but serve different purposes. For example, approving an invoice can create a domain event (`InvoiceApproved`), a workflow event (review task resolved and invoice status changed), and an audit event (user approved invoice X with amount Y).

## 6. Document Engine

`Document` is the root object because everything important starts as a file or generated artifact:

- e-mail attachment;
- PDF invoice;
- XML e-invoice;
- bank statement;
- Merit import;
- EMTA export;
- manual upload.

The document layer gives every file a stable identity before domain interpretation. It stores source, status, original filename, file location, checksum, MIME type, size, metadata, versions, tags, and timestamps.

This prevents later modules from duplicating file metadata. An invoice, bank statement, EMTA export, or Merit import should reference a document rather than reinventing file identity and storage fields.

## 7. Workflow Engine

The platform should use an event-driven process model. Instead of hiding business transitions inside views or scripts, important steps are recorded as workflow events.

Example event chain:

1. `DocumentReceived`
2. `DocumentParsed`
3. `SupplierMatched`
4. `UserCorrectedSupplier`
5. `LearningRuleCreated`
6. `InvoiceApproved`
7. `InvoiceSentToMerit`
8. `PaymentMatched`
9. `Archived`

Workflow events should support progress views, review queues, retries, audit trails, and future automation. They also make it easier to understand why a document is waiting, approved, blocked, sent, or archived.

## 8. Cognitive Layer Architecture

The Cognitive Layer is not only LLM/AI. It is the set of engines that turn raw documents, events, history, and company knowledge into explainable suggestions and reviewable decisions.

AI is not the system center. The center is business process, append-only events, and human-approved knowledge. The Cognitive Layer supports the process; it does not replace responsibility for accounting, tax, banking, or operational decisions.

### Processing Flow Example

```text
Document
-> OCR Engine
-> Extraction Engine
-> Validation Engine
-> Confidence Engine
-> Decision Engine
-> Review Engine if needed
-> Learning Engine
-> Knowledge Engine
```

### OCR Engine

Purpose: turn scanned documents, image PDFs, and low-quality attachments into machine-readable text and layout data.

Inputs: document file, document version, file type, image pages, PDF pages, prior OCR settings, language hints.

Outputs: OCR text, page-level layout, OCR quality metrics, extracted blocks, warnings, processing events.

Relationship to events: produces or supports `DocumentParsed`, `DocumentFailedParsing`, `ConfidenceChanged`, and processing job events.

Relationship to human review: low OCR quality should route the document to review or show extracted text beside the original file.

What it must not do: it must not decide supplier, VAT, project, payment, or accounting status by itself.

### Extraction Engine

Purpose: extract structured candidates from document text and metadata.

Inputs: OCR text, embedded PDF text, XML content, e-mail metadata, filename, document source, known supplier patterns, prompt outputs.

Outputs: candidate fields such as invoice number, issue date, due date, supplier, registry code, VAT number, IBAN, amounts, VAT rates, project codes, invoice lines, and raw extraction evidence.

Relationship to events: produces extraction results and events such as `SupplierDetected`, `InvoiceCandidateCreated`, `DocumentParsed`, and `ConfidenceChanged`.

Relationship to human review: extracted fields should be shown with evidence and confidence so users can correct them quickly.

What it must not do: it must not silently create approved accounting records or overwrite user-confirmed values.

### Validation Engine

Purpose: check extracted and entered data against rules, arithmetic, registries, historical data, and accounting constraints.

Inputs: extraction results, document metadata, invoice candidates, supplier data, VAT rules, line totals, bank data, Merit snapshots, company settings.

Outputs: validation results, warnings, blocking errors, explanations, suggested corrections.

Relationship to events: emits validation-related workflow events and can cause `ReviewTaskCreated`, `ConfidenceChanged`, or status transition events.

Relationship to human review: blocking errors and important warnings should be visible before approval or external API writes.

What it must not do: it must not hide failed validations or silently adjust accounting data without traceable user approval.

### Confidence Engine

Purpose: calculate confidence from multiple evidence sources and produce explainable confidence scores.

Inputs: OCR quality, extraction consistency, IBAN match, VAT number match, registry code match, supplier history, invoice number pattern, e-mail sender, previous corrections, layout similarity, amount arithmetic, duplicate checks, and validation results.

Outputs: normalized confidence score, confidence band, evidence list, negative signals, reasons, recommended review level.

Relationship to events: emits `ConfidenceChanged` and supports AI, workflow, learning, and review events.

Relationship to human review: confidence determines whether the user sees a fast confirmation, a full review task, or a warning that automation is not safe.

What it must not do: it must not treat LLM confidence as the whole truth. Confidence is evidence aggregation, not a model's self-assessment.

Confidence is not only LLM confidence. It combines evidence such as:

- OCR quality;
- IBAN match;
- VAT number match;
- registry code match;
- supplier history;
- invoice number pattern;
- e-mail sender;
- previous corrections;
- layout similarity.

Example thresholds:

- `> 99%`: automatic low-risk action may be allowed if the action is reversible and configured as low risk.
- `90-99%`: human confirmation required.
- `< 90%`: review required.

Thresholds must be configurable later by company, workflow, action type, risk level, and integration.

### Decision Engine

Purpose: choose the next proposed action based on events, confidence, validations, workflow state, permissions, and risk.

Inputs: confidence scores, validation results, workflow state, user permissions, company rules, learning rules, knowledge facts, integration state.

Outputs: suggested next action, required approval level, review task request, automation decision, event payload.

Relationship to events: all decisions emit events. A decision can produce `ReviewTaskCreated`, `InvoiceApproved`, `InvoiceRejected`, `InvoiceSentToMerit`, or a blocked/waiting state.

Relationship to human review: high-risk actions require confirmation; medium-confidence actions request review; low-risk actions can be batched or auto-applied only when configured.

What it must not do: it must not make silent accounting changes. AI suggests, workflow decides, and all decisions must be traceable.

### Review Engine

Purpose: route uncertain, high-risk, conflicting, or user-required items into human review.

Inputs: decision outputs, validation warnings, confidence bands, user roles, review queues, due dates, workflow state.

Outputs: review tasks, notifications, user decision records, correction prompts, status transitions.

Relationship to events: produces `ReviewTaskCreated`, `ReviewTaskResolved`, `UserCorrectionCreated`, status transitions, and audit events.

Relationship to human review: this engine is the human-in-the-loop surface of the platform.

What it must not do: it must not bury risky actions in notification noise or resolve review tasks without an explicit decision.

### Learning Engine

Purpose: learn from confirmed human corrections and repeated confirmed decisions.

Inputs: user corrections, accepted matches, repeated approvals, rejected suggestions, supplier aliases, account assignment corrections, project allocation corrections.

Outputs: learning rule candidates, rule activation suggestions, supplier memory updates, account assignment memory, pattern matches.

Relationship to events: consumes `UserCorrectionCreated`, `SupplierCorrected`, `InvoiceApproved`, and `ReviewTaskResolved`; emits `LearningRuleCreated` when a rule candidate or approved rule is created.

Relationship to human review: learning rules should be proposed before being applied automatically unless the rule type is explicitly configured as safe.

What it must not do: it must not learn from unverified AI guesses. It learns only from confirmed human corrections or repeated confirmed decisions.

### Knowledge Engine

Purpose: store company knowledge, not just extracted data.

Inputs: learning rules, user-approved exceptions, supplier memory, project allocation history, account assignment history, integration data, curated business notes.

Outputs: knowledge facts, knowledge relations, business memory entries, relevant context for reasoning and prompts.

Relationship to events: consumes learning, correction, approval, and integration events; emits `KnowledgeFactCreated` when confirmed knowledge is stored.

Relationship to human review: knowledge that can affect accounting decisions should be visible, editable, and reviewable.

What it must not do: it must not turn temporary guesses into permanent company knowledge.

Examples:

- supplier recognition patterns;
- project allocation patterns;
- account assignment patterns;
- recurring invoice behavior;
- approved exceptions.

### Business Reasoning Engine

Purpose: use history, rules, and knowledge to recommend business actions in a way users can understand.

Inputs: document data, invoice data, supplier history, project history, learning rules, knowledge facts, current workflow state, user permissions.

Outputs: explainable recommendations, suggested allocations, next actions, warnings, review reasons.

Relationship to events: consumes domain and workflow events; emits recommendation events or decision-support payloads that can create review tasks.

Relationship to human review: recommendations should be presented with reasons and evidence, especially when they affect accounting, project allocation, or external writes.

What it must not do: it must not present a recommendation without explainable evidence.

Example: "This supplier's last 143 invoices were assigned to project Kanarbiku. Suggest same project?"

### Prompt Engine

Purpose: manage prompt templates and make LLM behavior auditable and reproducible.

Inputs: prompt template, prompt version, selected document text, extracted candidates, relevant knowledge facts, task schema, model configuration.

Outputs: rendered prompt record, model output, parsed response, prompt/model metadata, token/context summary.

Relationship to events: creates AI job records and supports AI events such as `DocumentParsed`, `SupplierDetected`, `ConfidenceChanged`, and extraction result events.

Relationship to human review: LLM outputs should be reviewable with prompt version, source context, and resulting structured data.

What it must not do: it must not send unnecessary sensitive context to an LLM or make unlogged calls that cannot be audited.

The Prompt Engine should:

- manage prompt templates;
- limit context sent to the LLM;
- inject only relevant document text, candidates, and knowledge;
- log prompt version and model output;
- make LLM behavior auditable and reproducible.

## 9. Policy Layer Architecture

AI does not decide business actions directly. The Cognitive Layer provides evidence, suggestions, validation results, confidence scores, and recommendations. The Policy Layer applies company rules and decides whether an action is allowed, denied, or requires review. Workflow then executes allowed transitions and the Event Store records the decision.

The Policy Layer sits between business process/workflow and the Cognitive Layer:

```text
Cognitive Layer -> Evidence
Policy Layer -> Allowed/Denied/Needs Review
Workflow -> Executes transition
Event Store -> Records decision
```

Policy decisions consider company rules, risk level, confidence, user permissions, amount limits, supplier trust, history, and compliance rules.

Auto-approve invoice only if:

- confidence is greater than 99%;
- amount is below configured threshold;
- supplier is trusted;
- no VAT anomaly exists;
- no IBAN change exists;
- no duplicate risk exists.

Require human approval if:

- supplier is new;
- IBAN changed;
- amount is high;
- confidence is low;
- VAT is unusual;
- project is missing.

Never allow silent high-risk accounting changes.

### Policy Concepts

#### PolicyRule

Purpose: one explicit rule that allows, denies, requires review, or modifies an action.

Inputs: action type, company, user, target object, confidence score, validation results, risk level, history, supplier trust, amount.

Outputs: rule result, reason, severity, and evidence.

Relationship to events: policy evaluation emits decision-support events and can contribute to `PolicyDecision` audit payloads.

Relationship to audit: each rule that affected a high-risk decision should be traceable.

Future implementation notes: rules can begin as Django services and later become configurable records.

#### RiskLevel

Purpose: classify action risk so automation and review thresholds can differ by impact.

Inputs: action type, amount, external write flag, tax impact, bank impact, supplier trust, confidence, validation status.

Outputs: low, medium, high, or blocked risk classification.

Relationship to events: risk changes can produce `ConfidenceChanged`, review, or policy decision events.

Relationship to audit: risk classification explains why a user approval was required.

Future implementation notes: risk levels should be configurable by company and workflow.

#### ApprovalPolicy

Purpose: decide who must approve a proposed action.

Inputs: user role, amount, action type, risk level, supplier status, project presence, compliance checks.

Outputs: approval required/not required, required role, required user count, reason.

Relationship to events: creates review tasks and approval workflow events.

Relationship to audit: approval requirements and final approver decisions must be retained.

Future implementation notes: support single-user, role-based, and multi-step approvals later.

#### AutomationPolicy

Purpose: decide whether a low-risk action can run without manual review.

Inputs: confidence, risk level, validation status, action reversibility, company settings, historical success.

Outputs: allow automation, deny automation, or require review.

Relationship to events: emits policy decision events before automation transitions.

Relationship to audit: every automated action should state which policy allowed it.

Future implementation notes: automation should start conservative and expand only after enough evidence exists.

#### SupplierTrustPolicy

Purpose: decide whether a supplier is trusted for specific actions.

Inputs: supplier history, aliases, IBAN history, VAT/registry matches, prior corrections, prior approvals, external mappings.

Outputs: trust level, trust reasons, required review conditions.

Relationship to events: supplier trust changes can produce knowledge and learning events.

Relationship to audit: supplier trust must explain why automation was allowed or blocked.

Future implementation notes: trust is action-specific; a supplier may be trusted for recognition but not for IBAN changes.

#### AmountThresholdPolicy

Purpose: apply company-specific amount limits to approvals and automation.

Inputs: gross amount, currency, invoice type, user role, supplier trust, project, cost category.

Outputs: below threshold, above threshold, required approval level.

Relationship to events: threshold decisions can create review tasks or approval events.

Relationship to audit: amount thresholds explain approval requirements for high-value invoices and payments.

Future implementation notes: support currency conversion and category-specific thresholds later.

#### CompliancePolicy

Purpose: prevent or route actions that may violate tax, accounting, privacy, or integration rules.

Inputs: VAT validation, required fields, country rules, document status, user permissions, external API constraints.

Outputs: allowed, blocked, needs review, compliance message.

Relationship to events: compliance blocks produce validation and workflow events.

Relationship to audit: compliance results should remain visible in invoice, payment, and export history.

Future implementation notes: compliance policies should be explicit and tested before EMTA or bank API actions.

#### PolicyDecision

Purpose: final explainable result of policy evaluation for a proposed action.

Inputs: evaluated policy rules, risk level, confidence, user context, target object, proposed action.

Outputs: allowed, denied, needs review, required approver, reasons, evidence.

Relationship to events: policy decisions should be recorded as events and may trigger workflow transitions.

Relationship to audit: high-risk policy decisions are audit records.

Future implementation notes: use a stable payload shape so decisions can be shown in UI and replayed for debugging.

## 10. Capability Architecture

Capabilities are reusable technical abilities, not business modules. A business module such as accounting, project management, procurement, BIM, CRM, or reporting can use many capabilities. A capability should not contain business policy by itself; it performs a technical function and returns evidence, candidates, scores, or generated output.

### OCR Capability

Purpose: convert images and scanned PDFs to text and layout.

Typical inputs: document file, page images, language hints.

Typical outputs: text, blocks, coordinates, OCR quality metrics.

Business modules that may use it: accounting, procurement, CRM, project files, BIM document intake.

Relationship to Cognitive Layer: used by OCR Engine.

Future implementation notes: support multiple OCR providers and quality comparison.

### Document Parsing Capability

Purpose: parse PDFs, XML, Excel, e-mail bodies, and generated files.

Typical inputs: document file, MIME type, raw bytes, OCR text.

Typical outputs: normalized text, tables, metadata, attachments, structured fragments.

Business modules that may use it: accounting, bank import, EMTA export review, project management, procurement.

Relationship to Cognitive Layer: feeds Extraction and Validation engines.

Future implementation notes: preserve raw parser output for debugging.

### Classification Capability

Purpose: classify document or object type.

Typical inputs: filename, text, sender, metadata, source, prior tags.

Typical outputs: class candidates, confidence, reasons.

Business modules that may use it: accounting, workflow, CRM, document archive, procurement.

Relationship to Cognitive Layer: supports Decision and Review engines.

Future implementation notes: keep classification separate from final workflow status.

### Entity Extraction Capability

Purpose: extract names, dates, amounts, IBANs, VAT numbers, registry codes, project codes, and references.

Typical inputs: text, layout, XML fields, known patterns, knowledge facts.

Typical outputs: entity candidates, source spans, confidence, normalized values.

Business modules that may use it: accounting, CRM, procurement, project management, integrations.

Relationship to Cognitive Layer: used by Extraction Engine.

Future implementation notes: entity candidates should keep evidence spans.

### Supplier Matching Capability

Purpose: match extracted supplier evidence to known suppliers.

Typical inputs: name, IBAN, VAT number, registry code, e-mail sender, aliases, history.

Typical outputs: supplier candidates, score, reasons, conflicts.

Business modules that may use it: accounting, procurement, payments, CRM.

Relationship to Cognitive Layer: contributes to Confidence and Decision engines.

Future implementation notes: support merge/split workflows for supplier duplicates.

### Duplicate Detection Capability

Purpose: detect duplicate documents, invoices, transactions, or exports.

Typical inputs: checksum, invoice number, supplier, amount, dates, external ids, text similarity.

Typical outputs: duplicate candidates, score, reasons, recommended handling.

Business modules that may use it: accounting, document archive, integrations, bank import.

Relationship to Cognitive Layer: feeds Validation and Policy layers.

Future implementation notes: duplicate risk should block silent approval.

### Confidence Scoring Capability

Purpose: combine evidence into explainable confidence scores.

Typical inputs: OCR quality, matches, validation results, history, layout similarity, prior corrections.

Typical outputs: confidence score, band, reasons, negative signals.

Business modules that may use it: accounting, reconciliation, procurement, CRM, reporting.

Relationship to Cognitive Layer: used by Confidence Engine.

Future implementation notes: thresholds belong in Policy Layer, not inside this capability.

### LLM Prompting Capability

Purpose: execute managed LLM prompts against limited and relevant context.

Typical inputs: prompt template, selected text, candidates, schema, relevant knowledge.

Typical outputs: model response, parsed payload, prompt metadata, errors.

Business modules that may use it: accounting, quotations, CRM, project management, BI.

Relationship to Cognitive Layer: used by Prompt Engine and Business Reasoning Engine.

Future implementation notes: log prompt version, model, context summary, and output.

### Semantic Search Capability

Purpose: retrieve relevant documents, facts, rules, and history by meaning.

Typical inputs: query, embeddings, filters, company scope, object type.

Typical outputs: ranked results, snippets, references, scores.

Business modules that may use it: knowledge, CRM, quotations, project management, reporting.

Relationship to Cognitive Layer: feeds Knowledge and Business Reasoning engines.

Future implementation notes: must respect company/user permissions.

### Translation Capability

Purpose: translate foreign invoices, e-mails, product descriptions, and support text.

Typical inputs: text, source language, target language, glossary.

Typical outputs: translated text, detected language, confidence, warnings.

Business modules that may use it: accounting, procurement, CRM, project management.

Relationship to Cognitive Layer: supports extraction, review, and prompt context preparation.

Future implementation notes: retain original text as source of truth.

### Vision/Image Understanding Capability

Purpose: interpret images beyond OCR, such as photographed receipts, diagrams, damage photos, or visual document cues.

Typical inputs: image, page screenshot, document context, task prompt.

Typical outputs: visual observations, extracted visual fields, quality warnings.

Business modules that may use it: accounting, fleet, inventory, BIM/project documentation, CRM.

Relationship to Cognitive Layer: supports OCR, extraction, and review.

Future implementation notes: image-derived conclusions need evidence and review for high-risk actions.

### BIM/IFC Analysis Capability

Purpose: inspect BIM/IFC files and extract project, quantity, object, or model metadata.

Typical inputs: IFC/BIM file, object filters, project context.

Typical outputs: object lists, quantities, classifications, conflicts, references.

Business modules that may use it: BIM tools, project management, procurement, quotations.

Relationship to Cognitive Layer: future specialized capability feeding business reasoning.

Future implementation notes: keep BIM logic modular so accounting does not depend on it.

### Spreadsheet Understanding Capability

Purpose: interpret Excel/CSV/TSV files with tables, statements, price lists, budgets, or reports.

Typical inputs: spreadsheet file, sheet names, table ranges, formulas, headers.

Typical outputs: normalized tables, detected schemas, validation warnings.

Business modules that may use it: accounting, banking, procurement, inventory, BI.

Relationship to Cognitive Layer: supports extraction, validation, and export review.

Future implementation notes: preserve sheet/cell references as evidence.

### E-mail Understanding Capability

Purpose: understand e-mail sender, thread, body, signatures, attachments, and intent.

Typical inputs: e-mail headers, body, sender, recipients, attachments, thread metadata.

Typical outputs: document candidates, intent, sender classification, attachment relationships.

Business modules that may use it: accounting, CRM, procurement, project communication.

Relationship to Cognitive Layer: supports document intake and classification.

Future implementation notes: separate e-mail metadata from attachment-derived facts.

### Reconciliation Capability

Purpose: match records across domains such as invoices, bank transactions, Merit records, and documents.

Typical inputs: invoices, transactions, external records, amounts, dates, references, parties.

Typical outputs: match candidates, scores, reasons, unmatched lists.

Business modules that may use it: accounting, banking, integrations, reporting.

Relationship to Cognitive Layer: supports Confidence, Decision, and Review engines.

Future implementation notes: every match needs reasons, not only a score.

### Export Generation Capability

Purpose: generate files or payloads for external systems and reporting.

Typical inputs: approved domain objects, templates, schemas, company settings, validation results.

Typical outputs: XML, CSV, JSON, PDF, API payloads, preview data, validation report.

Business modules that may use it: EMTA, Merit, bank payments, reporting, procurement.

Relationship to Cognitive Layer: may use validation and reasoning, but final permission comes from Policy Layer.

Future implementation notes: exported artifacts should become documents and be linked to events.

## 11. Learning Engine

The system learns from confirmed user actions and repeated high-confidence outcomes.

Learning sources include:

- supplier corrections;
- IBAN matches;
- VAT number matches;
- invoice layout patterns;
- project code corrections;
- account/category corrections;
- repeated user confirmations.

Learning outputs can include supplier aliases, extraction hints, project allocation rules, account selection defaults, invoice layout fingerprints, and payment matching rules.

A learning rule should contain evidence: what was corrected, by whom, when, how often it repeated, and which future cases it applies to.

## 12. Knowledge Engine

The platform should capture company knowledge, not only data.

Examples:

- supplier recognition rules;
- project allocation patterns;
- account selection patterns;
- recurring invoice behavior;
- user-approved exceptions.

Knowledge facts should be reusable by AI prompts, matching algorithms, workflow decisions, and reporting. They should also be reviewable, because outdated company knowledge can become a source of systematic errors.

## 13. Accounting Module

The accounting module will build on the document, workflow, AI, learning, and integration layers.

Future accounting flows include:

- purchase invoice intake and review;
- own sales invoice recognition and separation;
- invoice line extraction;
- VAT amount/rate validation;
- Merit sync for suppliers, projects, invoices, and payments;
- payment status tracking;
- bank transaction matching;
- EMTA KMD/KMD INF export preview.

Accounting objects must preserve enough evidence to answer:

- Where did this invoice come from?
- Which document and version produced this data?
- What did AI extract?
- What did the user correct?
- What was sent to Merit?
- Which bank transaction paid it?
- What is included in an EMTA preview?

## 14. Integrations

Planned integrations include:

- Outlook/PST/IMAP/Microsoft 365 for e-mail and attachments;
- Merit Aktiva for suppliers, projects, purchase invoices, sales invoices, and payment status;
- Swedbank/SEB/LHV bank statements, initially via ISO XML 052 imports and later via API where feasible;
- EMTA for VAT declaration export workflows;
- SharePoint/OneDrive/Google Drive for document storage and shared files;
- future REST API for external tools and internal automation.

Integrations should separate read sync from write operations. Reads can often be automated. Writes to accounting, banking, or tax systems need previews, confirmation, audit logs, and stored request/response records.

## 15. Security and Audit

Security and audit requirements:

- company separation must be explicit in future multi-company data models;
- user roles must separate viewing, correcting, approving, exporting, and external API writing;
- audit logs must capture important business actions;
- sensitive data such as invoices, bank statements, API keys, and personal data must stay out of Git;
- AI decision traceability must show source data, prompt/job context, confidence, and user confirmation status.

The system should treat accounting and banking data as sensitive by default.

## 16. Migration Strategy

The legacy app remains working while the Django platform grows in parallel. Migration happens module by module, not through a large rewrite.

Reusable legacy modules include:

- `detection.py`
- `invoice_extract.py`
- `invoice_project_lines.py`
- `bank_import.py`
- `reconcile_bank.py`
- `merit_api_client.py`
- `merit_api_payload.py`
- `sepa_payment.py`

Reusable code should be extracted into framework-light services where practical. Django views should call services; they should not become the home of parsing, matching, accounting, or integration rules.

The legacy UI can remain the daily tool until replacement workflows are stable in Django.

## 17. Future Modules

Future business modules can reuse the same platform foundations:

- quotation AI;
- project management;
- BIM/IFC tools;
- procurement;
- inventory;
- CRM;
- fleet management;
- reporting/business intelligence.

These modules should not start from scratch. They should use documents, workflows, AI jobs, learning rules, knowledge facts, integrations, notifications, and audit events.

## 18. Engineering Rules

- Work in small tasks.
- Use one commit per task.
- Legacy tests must stay green.
- Django tests must stay green.
- Do not do large rewrites without architecture approval.
- Codex implements; architecture decisions are documented first.
- Keep real business data out of Git.
- Add migrations only when domain models change.
- Keep external API writes explicit, logged, and confirmed.

## 19. Roadmap Alignment

Current phase:

- TASK-001 repository foundation done.
- TASK-002 Django platform skeleton done.
- TASK-003 Document Engine foundation done.
- Next planned: Workflow Engine foundation.

This document should guide future tasks so the accounting module grows as the first module of a larger AI Business Operating System, not as a narrow one-off invoice script.
