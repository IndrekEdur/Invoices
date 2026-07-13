# Architecture Decisions

This file records important project decisions. New decisions should be appended rather than rewriting history.

## ADR-001: Keep the Current Prototype Working During Migration

Date: 2026-06-27

Decision:

- Do not replace the current local app in one rewrite.
- Keep it working while a Django/PostgreSQL implementation is introduced beside it.

Reason:

- The current app contains valuable business knowledge and tested edge cases.
- A big-bang rewrite would risk losing invoice extraction, bank matching, and Merit API behavior.

## ADR-002: Use Django + PostgreSQL + HTMX as Target Architecture

Date: 2026-06-27

Decision:

- Use Django for backend, models, migrations, admin, forms, and templates.
- Use PostgreSQL for durable structured data.
- Use HTMX for interactive server-rendered workflows.

Reason:

- The product is mostly review tables, forms, reconciliation screens, and audit workflows.
- Django provides strong defaults for this kind of internal business application.
- HTMX avoids unnecessary frontend complexity while still supporting responsive workflows.

## ADR-003: Keep Real Business Data Out of Git

Date: 2026-06-27

Decision:

- Do not commit SQLite databases, invoice PDFs/XMLs, bank statements, generated CSVs, logs, or scan folders.

Reason:

- The repository may contain sensitive accounting and banking context.
- Source control should contain code, tests, and documentation only.

## ADR-004: Treat Matching Scores as Explainable Evidence

Date: 2026-06-27

Decision:

- Matching logic should return score, reasons, and matched fields.
- Final accounting decisions should remain reviewable and auditable.

Reason:

- Invoice and bank data are messy.
- False positives can have accounting consequences.
- Users need to understand why a match was proposed.

## ADR-005: External API Writes Must Be Audited

Date: 2026-06-27

Decision:

- Merit invoice sends, payment sends, and project creation should have stored request/response records.

Reason:

- External accounting API writes are important business events.
- Retries and "already exists/already paid" responses must be explainable later.

## ADR-006: Build the Document Engine Before Accounting Models

Date: 2026-06-27

Decision:

- Add the Django document model layer before invoice, company, accounting, audit, or integration-specific domain models.
- Treat imported and generated files as first-class records that later workflows can reference.

Reason:

- Invoices, bank statements, Merit imports, EMTA exports, and manual uploads all begin as files.
- Stable document identity, checksums, versions, tags, and source/status metadata reduce duplication in later accounting models.
- This keeps the first Django domain step useful without migrating legacy business logic yet.

## ADR-007: Create Master Architecture Before Continuing Domain Expansion

Date: 2026-06-27

Decision:

- Create `MASTER_ARCHITECTURE.md` as the central long-term architecture reference before adding more domain models.
- Use it to align accounting automation with the broader AI Business Operating System vision.

Reason:

- The product is expanding beyond invoice automation.
- Future modules need shared platform layers, domain vocabulary, and engineering rules.
- Architecture decisions should be documented before Codex continues implementation tasks.

## ADR-008: Design the Domain Model Before Expanding Implementation

Date: 2026-06-27

Decision:

- Expand the master architecture domain model before adding more Django models or migrations.
- Treat `Document` and event history as platform roots, with accounting objects derived downstream.

Reason:

- The platform is becoming an AI Business Operating System, not only an invoice register.
- Detailed domain vocabulary reduces the risk of prematurely coupling accounting, AI, workflow, learning, and integration concepts.
- Future implementation tasks should be small and aligned with the domain design before code is added.

## ADR-009: Event Model Is Append-Only and Becomes the Backbone of Audit and Learning

Date: 2026-06-27

Decision:

- Important platform changes must be recorded as append-only events.
- Event history becomes a shared foundation for audit, learning, debugging, automation, and future AI agents.

Reason:

- Accounting, banking, tax, integration, and AI decisions must remain traceable.
- Learning from corrections requires reliable historical evidence.
- Append-only events preserve what happened even when a later correction changes business state.

## ADR-010: Use Cognitive Layer Instead of Generic AI Engine

Date: 2026-06-28

Decision:

- Replace the generic AI Engine concept with a broader Cognitive Layer architecture.
- Include OCR, extraction, validation, confidence, decision support, review, learning, knowledge, business reasoning, and prompt management as separate responsibilities.

Reason:

- The platform needs more than LLM calls.
- Accounting and operational decisions require evidence, validation, confidence scoring, human review, and auditability.
- AI should support business process, events, and human-approved knowledge rather than becoming the center of the system.

## ADR-011: Add Policy Layer Between Business Workflow and Automation

Date: 2026-06-28

Decision:

- Add a Policy Layer between business workflow and automation.
- Let the Cognitive Layer provide evidence, while the Policy Layer decides whether an action is allowed, denied, or requires review.

Reason:

- AI and confidence scores should not directly perform business actions.
- Company rules, risk, permissions, amount limits, supplier trust, and compliance checks must govern automation.
- High-risk accounting, banking, tax, and integration changes must never happen silently.

## ADR-012: Treat Technical Abilities as Reusable Capabilities

Date: 2026-06-28

Decision:

- Treat OCR, LLM prompting, BIM/IFC analysis, semantic search, reconciliation, export generation, and similar technical abilities as reusable capabilities.
- Keep capabilities separate from business modules and policy decisions.

Reason:

- Many future modules need the same technical abilities.
- Reuse prevents accounting, CRM, project, BIM, and BI modules from reimplementing similar logic.
- Capabilities should return evidence, candidates, scores, or generated output; business policy decides what can be done with them.

## ADR-013: Platform Root Entity Is Organization and Business Entities Are Party Roles

Date: 2026-06-28

Decision:

- The platform root entity is `Organization`.
- Business entities such as Supplier and Customer are modeled as Party roles.
- Accounting modules operate inside an Organization rather than defining the platform core.

Reason:

- The product is a Cognitive Business Platform, not only an accounting application.
- Organization can represent a Company, Sole Proprietor, Non-profit, Government, or Other tenant type.
- Party separates legal or natural person identity from module-specific roles such as supplier, customer, partner, contractor, employee, bank, or tax authority.

## ADR-014: Enterprise Domain Map Becomes a First-Class Project Document

Date: 2026-06-29

Decision:

- Add `ENTERPRISE_DOMAIN_MAP.md` as a first-class project document.
- Use it to describe the business-level domain map: what the organization knows, remembers, communicates, and acts on.

Reason:

- The platform is broader than invoice automation or technical architecture.
- Business memory, communication, decisions, projects, parties, and knowledge need a shared vocabulary understandable to non-programmers.
- Separating the business domain map from technical architecture keeps implementation documents focused while preserving the broader product vision.

## ADR-015: Communication Is a First-Class Business Domain

Date: 2026-06-29

Decision:

- Treat communication as a first-class business domain, not only an e-mail integration.
- Create `COMMUNICATION_ARCHITECTURE.md` to define how e-mails, meetings, calls, chats, questions, answer drafts, and communication learning fit into organization memory.

Reason:

- Important business context often lives in mailboxes, meeting notes, calls, and chat messages.
- Attachments alone are not enough; the message, thread, participants, project context, questions, and answers are business memory.
- Communication needs its own domain vocabulary before implementation begins.

## ADR-016: Project Becomes the Primary Business Context of the Platform

Date: 2026-06-30

Decision:

- Treat Project as the primary business context of the platform.
- Create `PROJECT_ARCHITECTURE.md` to describe how projects connect people, communications, documents, workflows, accounting, knowledge, and AI reasoning.

Reason:

- Many business objects need project context to be understood correctly.
- Projects act as organizational memory containers for evidence, decisions, tasks, timelines, and relationships.
- A shared Project Domain architecture is needed before implementation introduces project models or project-based automation.

## ADR-017: Implement Complete Business Scenarios Before Isolated Technical Modules

Date: 2026-06-30

Decision:

- The platform shall be implemented using complete business scenarios rather than isolated technical modules.
- Use `EMAIL_PROCESSING_EPIC.md` as the first scenario-level reference for incoming business e-mail processing.

Reason:

- The platform's value comes from end-to-end business outcomes, not separate disconnected features.
- E-mail processing connects communication, projects, documents, workflows, AI reasoning, accounting, learning, and business memory.
- Scenario-level epics help future implementation tasks stay aligned with real user workflows.

## ADR-018: Knowledge Engine Becomes the Controlled Memory and AI Context Layer

Date: 2026-07-07

Decision:

- The Knowledge Engine becomes the controlled memory and AI context layer of the platform.
- It turns communications, documents, workflow events, audit events, user confirmations, decisions, and future accounting outcomes into reusable business knowledge.
- Future AI and reasoning services should receive context through Knowledge Engine builders and providers rather than querying arbitrary domain tables directly.

Reason:

- Business recommendations must be explainable through evidence, timeline, source references, and human confirmations.
- AI context must be reproducible and auditable.
- Human-confirmed facts are more trustworthy than unverified AI guesses.
- Separating knowledge from learning, policy, workflow, and AI keeps future automation safer and easier to debug.

## ADR-019: Platform UI Is a Business Workspace, Not a Django Admin Replacement

Date: 2026-07-07

Decision:

- The platform user interface shall be designed as a business workspace, not a Django Admin replacement.
- Normal users should work through role-specific dashboards, inboxes, project workspaces, review queues, document workspaces, search, and AI assistant panels.
- Django Admin remains a developer/admin tool for low-level operations, not the main product interface.

Reason:

- The platform must help users make business decisions, not expose database tables.
- AI suggestions, review queues, evidence, workflow state, and project context need dedicated UX patterns.
- Project managers, site managers, electricians, accounting users, administrators, and management have different daily workflows.
- Trustworthy automation requires visible evidence, human confirmation, and clear action controls.

## ADR-020: Operations Workspace Platform Governs Business Engines and AI Capabilities

Date: 2026-07-07

Decision:

- The Operations Workspace Platform becomes the top-level architectural concept governing all business engines and future AI capabilities.
- The product is a business workspace where communication, projects, documents, workflow, knowledge, accounting, integrations, and AI assistance work together.
- ERP, CRM, document archive, and e-mail-client capabilities are orchestrated inside one operational context rather than treated as isolated products.

Reason:

- Daily operational work crosses system boundaries.
- AI needs verified knowledge, evidence, workflow, and human review to be useful and safe.
- A workspace architecture keeps the product business-first while still allowing modular engines and future capabilities to grow independently.
- This concept aligns UI, domain models, knowledge, policy, integrations, audit, and future AI assistance under one shared architecture.

## ADR-021: First Product Milestone Is a Production-Usable Operations Workspace MVP

Date: 2026-07-08

Decision:

- The first product milestone shall be a production-usable Operations Workspace MVP focused on replacing daily operational workflows before expanding functionality.
- The MVP should let a real installation company receive e-mail, confirm project context, open documents, review AI suggestions, search history, and work from one browser workspace.
- Future modules should grow from this complete daily workflow instead of isolated technical features.

Reason:

- The platform's value is proven only when users can perform daily work inside it.
- A complete but narrow workflow is more useful than many disconnected partial modules.
- Replacing Outlook/folder/manual search habits requires a coherent workspace with Inbox, Projects, Documents, Reviews, Search, AI assistance, Security, and Administration.
- Production usability requires authentication, organization isolation, permissions, audit, review, and evidence from the beginning.

## ADR-022: Merit Dimensions Synchronize with Workspace Project Codes Through Explicit Integration Services

Date: 2026-07-08

Decision:

- Merit dimensions shall be synchronized with Workspace project codes through explicit integration services and user-approved accounting actions.
- Workspace `Project.code` should correspond to Merit `Dimension.code`.
- Merit API logic must live behind connector/service boundaries, not inside Project models, templates, or generic workspace views.
- Creating or changing Merit dimensions requires explicit user approval unless a future Policy Layer allows automation.

Reason:

- Workspace manages operational project context while Merit remains the accounting system.
- Project dimensions affect accounting and must be auditable, explainable, and conflict-aware.
- Existing Merit dimensions must be imported before creating new project codes to prevent duplicates and preserve historical accounting context.
- Clear integration boundaries reduce risk when future invoice export, payment sync, and project dimension workflows are added.

## ADR-023: Platform Configuration Is Managed Through Settings Workspace

Date: 2026-07-10

Decision:

- Platform configuration shall be managed through a Settings Workspace rather than shell commands, direct database edits, or Django Admin as the normal user interface.
- Settings is the operational control center for organizations, users, roles, e-mail accounts, accounting integrations, Merit settings, project numbering, secrets, sync health, AI/knowledge configuration, audit, and system health.
- Workspace settings views must call service-layer APIs and connector boundaries instead of embedding provider-specific logic.
- Sensitive changes must be organization-scoped, permission-controlled, and audited.

Reason:

- Normal administrators should be able to configure and operate the platform without developer tools.
- Secrets, integrations, external writes, and automation settings are high-risk and need explicit UI, safe defaults, masking, permission checks, and audit trails.
- E-mail sync, Merit sync, project code allocation, and future AI settings must be understandable and testable before activation.
- A Settings Workspace keeps operational configuration aligned with the platform's service-layer, audit, policy, and integration architecture.

## ADR-024: Large Mailboxes Are Indexed Incrementally With Lazy Attachment Storage

Date: 2026-07-12

Decision:

- Large mailboxes shall be imported incrementally as searchable message and attachment indexes.
- Attachment binaries shall use lazy download and external storage instead of immediate full-mailbox binary import.
- Remote deletion shall not automatically remove Workspace business history.
- Attachment occurrence, stored binary object, and business `Document` are separate identities.
- Historical imports must be resumable, observable, idempotent, and safe to retry.

Reason:

- A production mailbox may contain 50 GB or more of data, mostly attachments.
- Downloading and processing every attachment immediately would create performance, storage, memory, and reliability risks.
- The Workspace is operational memory, not an IMAP mirror; business history must survive mailbox reorganization, deletion, or account disconnection.
- Separating message index, attachment manifest, binary storage, and business documents keeps storage scalable and preserves service boundaries.

## ADR-025: Project Financial Reporting Uses Synchronized Merit Read Models

Date: 2026-07-12

Decision:

- Project financial reporting shall be built from synchronized Merit general-ledger transactions, invoices, and payments.
- Merit remains the accounting system of record.
- Workspace provides project allocations, reconciliation, alerts, explainable aggregation, and controlled report distribution.
- General ledger rows, invoice records, payment records, source documents, and bank evidence remain separate but linkable identities.
- Financial reports must be auditable, reproducible, period-aware, organization-scoped, and drillable to source records.

Reason:

- Project managers and management need project financial visibility inside the operational workspace without replacing Merit.
- Final project result and margin require booked GL data, not only invoice gross totals.
- Missing invoices, unpaid invoices, source-document gaps, and unmatched bank payments require reconciliation across accounting, documents, e-mail, and bank evidence.
- Financial reporting is high-risk; uncertain matches, external report delivery, and accounting-impacting decisions require evidence, policy, permissions, and audit.

## ADR-026: Management Cost Allocation Is Separate From Merit GL Cache

Date: 2026-07-13

Decision:

- Management cost allocation shall be a separate internal reporting layer on top of synchronized Merit GL cache and project financial aggregation.
- Merit remains the accounting source of truth.
- Synchronized GL batches, entries, and allocations must not be modified by management allocation workflows.
- Approved management allocations are versioned, immutable, reversible through superseding versions, and auditable.
- Project reports must distinguish direct accounting cost from allocated management cost.

Reason:

- Indirect costs such as office, administration, management, vehicles, IT, warehouse, insurance, and project manager time are needed for internal profitability reporting.
- These allocations are management accounting decisions, not source accounting entries.
- Keeping them separate preserves trust in Merit-sourced data while allowing Workspace to support internal project profitability, department profitability, future alerts, and management reports.
- Versioning and audit make later corrections explainable without rewriting historical source data.

## ADR-027: Management Allocations Support Cost Pool And Workspace Project Sources

Date: 2026-07-13

Decision:

- Management allocations shall use one lifecycle for multiple allocation source types instead of creating separate workflows.
- Supported source types are `cost_pool` and `workspace_project`.
- Cost pool versions are identified by period and pool.
- Workspace Project versions are identified by period and source Project.
- A Workspace Project source uses direct project cost from `ProjectFinancialAggregationService`, not raw GL summing in Workspace code.
- The source Project cannot also be a recipient Project.
- Project Financials must distinguish allocated-in, allocated-out, net management allocation, and management total cost.

Reason:

- Internal management allocations sometimes redistribute indirect cost pools and sometimes redistribute direct cost from one operational Project to other Projects.
- Reusing one proposal, review, approval, revision, and audit lifecycle keeps the feature understandable and avoids duplicate workflows.
- Source identity and allocated-out reporting prevent source-project allocations from double-counting direct cost.
- Keeping the source amount derived from the existing financial aggregation service preserves traceability and avoids new accounting logic in views or templates.
