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
