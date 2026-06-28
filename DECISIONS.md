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
