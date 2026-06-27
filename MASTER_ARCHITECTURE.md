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

### AI Engine

The AI Engine performs OCR, parsing, extraction, matching, classification, duplicate detection, confidence scoring, prompt execution, and AI job logging.

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

## 4. Domain Model Overview

Future domain objects include:

- `Document`: root record for every imported or generated file.
- `DocumentVersion`: version history for replaced, transformed, or regenerated files.
- `DocumentTag`: lightweight classification attached to documents.
- `WorkflowEvent`: event log for domain process transitions and review actions.
- `Company`: tenant/business context for data separation.
- `User/Profile`: human actor, permissions, and personal workflow preferences.
- `AuditEvent`: durable record of important business and system decisions.
- `Supplier`: known supplier or business partner.
- `SupplierAlias`: alternative supplier names, e-mails, IBANs, VAT numbers, and matching hints.
- `Invoice`: purchase or sales invoice header.
- `InvoiceLine`: invoice row with amount, VAT, account, project, and item/category data.
- `BankStatement`: imported bank statement document and statement-level metadata.
- `BankTransaction`: individual bank transaction from an imported statement.
- `Payment`: payment record linked to invoices, bank transactions, and external accounting systems.
- `Project/Dimension`: project, object, dimension, or cost allocation reference.
- `IntegrationAccount`: configured connection to Merit, banks, Outlook, EMTA, or storage providers.
- `AIJob`: logged AI/OCR/parsing/matching job with prompt, model, input reference, output, and confidence.
- `LearningRule`: confirmed reusable rule derived from user corrections or repeated behavior.
- `KnowledgeFact`: structured company knowledge that can support future decisions.
- `Notification`: user-facing prompt, warning, task, or approval request.

## 5. Document Engine

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

## 6. Workflow Engine

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

## 7. AI Engine

The AI Engine supports:

- OCR for scanned documents and low-quality PDFs;
- parsing of PDF, XML, Excel, e-mail, and text;
- supplier detection;
- duplicate detection;
- VAT validation;
- project detection;
- payment matching;
- confidence scoring;
- prompt templates;
- AI job logging.

AI outputs must be stored with context: input reference, prompt/template version, model/provider if relevant, output payload, confidence, reasons, and errors. A user should be able to see why an AI result was proposed and whether it was accepted, corrected, or rejected.

AI should make low-risk automation faster and high-risk decisions clearer, but it should not silently create accounting consequences.

## 8. Learning Engine

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

## 9. Knowledge Engine

The platform should capture company knowledge, not only data.

Examples:

- supplier recognition rules;
- project allocation patterns;
- account selection patterns;
- recurring invoice behavior;
- user-approved exceptions.

Knowledge facts should be reusable by AI prompts, matching algorithms, workflow decisions, and reporting. They should also be reviewable, because outdated company knowledge can become a source of systematic errors.

## 10. Accounting Module

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

## 11. Integrations

Planned integrations include:

- Outlook/PST/IMAP/Microsoft 365 for e-mail and attachments;
- Merit Aktiva for suppliers, projects, purchase invoices, sales invoices, and payment status;
- Swedbank/SEB/LHV bank statements, initially via ISO XML 052 imports and later via API where feasible;
- EMTA for VAT declaration export workflows;
- SharePoint/OneDrive/Google Drive for document storage and shared files;
- future REST API for external tools and internal automation.

Integrations should separate read sync from write operations. Reads can often be automated. Writes to accounting, banking, or tax systems need previews, confirmation, audit logs, and stored request/response records.

## 12. Security and Audit

Security and audit requirements:

- company separation must be explicit in future multi-company data models;
- user roles must separate viewing, correcting, approving, exporting, and external API writing;
- audit logs must capture important business actions;
- sensitive data such as invoices, bank statements, API keys, and personal data must stay out of Git;
- AI decision traceability must show source data, prompt/job context, confidence, and user confirmation status.

The system should treat accounting and banking data as sensitive by default.

## 13. Migration Strategy

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

## 14. Future Modules

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

## 15. Engineering Rules

- Work in small tasks.
- Use one commit per task.
- Legacy tests must stay green.
- Django tests must stay green.
- Do not do large rewrites without architecture approval.
- Codex implements; architecture decisions are documented first.
- Keep real business data out of Git.
- Add migrations only when domain models change.
- Keep external API writes explicit, logged, and confirmed.

## 16. Roadmap Alignment

Current phase:

- TASK-001 repository foundation done.
- TASK-002 Django platform skeleton done.
- TASK-003 Document Engine foundation done.
- Next planned: Workflow Engine foundation.

This document should guide future tasks so the accounting module grows as the first module of a larger AI Business Operating System, not as a narrow one-off invoice script.
