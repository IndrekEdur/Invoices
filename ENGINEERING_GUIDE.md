# Engineering Guide

This document defines how software is developed in this repository.

`MASTER_ARCHITECTURE.md` defines what the Cognitive Business Platform is.

`ENGINEERING_GUIDE.md` defines how it is built.

## 1. Engineering Philosophy

The platform should be built through small, deliberate steps. Every change should be understandable, testable, and reversible.

Core principles:

- Prefer small incremental changes.
- Keep one purpose per commit.
- Make architecture decisions before implementation.
- Update documentation before major features.
- Put business process before technology choices.
- The Cognitive Layer supports decisions; it never silently changes accounting.
- Prefer simplicity over cleverness.
- Prefer long-term maintainability over short-term speed.

Good engineering here means preserving working behavior while steadily moving toward the target architecture.

## 2. Repository Structure

Current and target repository areas:

- `pst_invoice_finder/`: current legacy local application package. It contains valuable working business logic and must remain stable during migration.
- `platform/`: new Django platform. New long-term implementation work happens here unless a task explicitly targets the legacy app.
- `tests/`: legacy app regression tests.
- `platform/apps/*/tests.py`: Django app tests.
- `MASTER_ARCHITECTURE.md`: authoritative product and platform architecture.
- `ARCHITECTURE.md`: shorter architecture summary and transition notes.
- `ARCHITECTURE_REVIEW.md`: architecture review of the current state and migration direction.
- `SPECIFICATION.md`: product and behavior specification.
- `ROADMAP.md`: implementation direction and current phase notes.
- `DECISIONS.md`: architecture decision record.
- `CONTRIBUTING.md`: collaboration and contribution notes.
- `engineering/`: future home for engineering-specific references if this guide grows into multiple files.
- `docs/`: future home for user-facing or broader project documentation if needed.

The legacy app and Django platform coexist because the legacy app is already useful and contains domain knowledge. The Django platform grows beside it until replacement workflows are tested and safe.

## 3. Django Application Rules

Every domain area should have its own Django app. App boundaries should reflect business ownership, not just technical convenience.

Planned or existing apps:

- `core`: shared platform primitives, organization context, common utilities.
- `documents`: document records, versions, tags, and document lifecycle.
- `workflow`: workflow events, review routing, process state.
- `accounting`: invoices, invoice lines, VAT, payments, accounting flows.
- `banking`: bank statements, bank transactions, payment matching.
- `policy`: policy rules, approvals, automation limits, compliance decisions.
- `cognitive`: OCR, extraction, validation, confidence, decision support.
- `knowledge`: knowledge facts, business memory, knowledge relations.
- `learning`: corrections, learning rules, memories, pattern candidates.
- `notifications`: review tasks, notifications, user decisions.
- `integrations`: Merit, banks, Outlook, EMTA, storage providers, APIs.
- `capabilities`: reusable technical abilities such as OCR, search, LLM prompting, translation, BIM, and export generation.

Ownership rule: each app owns its models, services, events, selectors, validators, admin, and tests. Other apps should depend on public services/selectors, not private internals.

## 4. Folder Structure Rules

As apps grow, use a consistent layout:

```text
apps/example/
  models/
  services/
  events/
  selectors/
  validators/
  admin/
  tests/
  api/
  management/
```

Folder purposes:

- `models/`: database models and simple model helpers.
- `services/`: business actions and write-side logic.
- `events/`: event definitions, emitters, and handlers.
- `selectors/`: read-side queries and lookup helpers.
- `validators/`: validation rules that return structured results.
- `admin/`: Django admin configuration.
- `tests/`: unit, integration, workflow, and regression tests.
- `api/`: HTTP/API views and serializers if needed.
- `management/`: Django management commands.

Small apps can start with single files. Split into folders when the file becomes too broad or when the app needs clear ownership boundaries.

## 5. Models

Models represent data. They should stay boring.

Allowed in models:

- fields;
- constraints;
- indexes;
- relationships;
- simple helper methods such as `__str__`, status predicates, and safe formatting;
- small state helper methods when they do not hide business rules.

Avoid in models:

- external API calls;
- multi-step business workflows;
- AI/LLM calls;
- policy decisions;
- file parsing;
- bank reconciliation;
- Merit writes;
- EMTA export logic.

Business logic belongs in services, policies, validators, and capabilities.

## 6. Services

Services contain business logic. They coordinate models, validators, policies, events, integrations, and capabilities.

Examples:

- `SupplierMatchingService`
- `InvoiceBuilder`
- `PolicyEngine`
- `KnowledgeUpdater`
- `BankReconciliationService`
- `MeritInvoiceSender`
- `DocumentIntakeService`

Service rules:

- Business code should use domain services when available instead of creating important domain models directly. For example, use `AuditService.record(...)` instead of `AuditEvent.objects.create(...)`.
- Service inputs should use Command objects whenever multiple business parameters are required. A Command object gives the action a named input shape, keeps method signatures stable as fields are added, and makes service calls easier to test and review.
- One service method should perform one clear business action.
- Services should emit events for important changes.
- Services should return structured results, not only booleans.
- Services should be testable without the web UI.
- Services should not hide high-risk side effects.

## 7. Events

Everything important emits events.

Event rules:

- Events are append-only.
- Events are immutable.
- Events are never edited.
- Corrections create new events.
- Events should include actor, target, time, event type, correlation id, causation id, and payload.

Events support audit, learning, debugging, automation, progress views, and future cognitive agents.

`AuditEvent` is not the same thing as `DomainEvent`. `DomainEvent` describes something that happened inside the domain and may drive workflow, learning, integration handlers, or automation. `AuditEvent` exists for compliance and traceability: it records human and system actions in an append-only audit log so important decisions can be reviewed later.

Workflow models define process structure: definitions, states, and transitions. Workflow instances execute process for a specific business object. Keep those concepts separate so reusable workflow structure does not become coupled to invoices, documents, payments, or any other domain object.

## 8. Policies

Policies decide.

The Cognitive Layer provides evidence. Workflow executes allowed transitions. Policies decide whether an action is allowed, denied, or requires review.

Policy rules should consider:

- confidence;
- risk level;
- organization settings;
- user permissions;
- amount thresholds;
- supplier trust;
- VAT anomalies;
- duplicate risk;
- IBAN changes;
- compliance constraints.

Policies must remain configurable over time. Hard-coded policy should be treated as a temporary step, not the final architecture.

## 9. Cognitive Layer

The Cognitive Layer is responsible for interpreting documents and evidence.

Responsibilities:

- OCR;
- extraction;
- validation;
- confidence scoring;
- decision support;
- review routing support;
- prompt management;
- business reasoning support.

LLM is only one capability inside the Cognitive Layer. The platform should also use deterministic parsers, validators, matching algorithms, known business rules, historical evidence, and human-approved knowledge.

The Cognitive Layer must not silently change accounting data. It suggests, explains, and produces evidence.

## 10. Knowledge Layer

Knowledge survives model upgrades.

Knowledge is independent from any single LLM, prompt, model provider, or extraction implementation. It represents organization-specific understanding such as:

- supplier recognition rules;
- project allocation patterns;
- account assignment patterns;
- recurring invoice behavior;
- approved exceptions;
- trusted suppliers;
- known document layouts.

Knowledge should be traceable to sources: user corrections, repeated approvals, integration data, or curated business rules.

## 11. Capability Layer

Capabilities are reusable technical abilities.

Examples:

- OCR;
- search;
- LLM prompting;
- translation;
- vision/image understanding;
- BIM/IFC analysis;
- spreadsheet understanding;
- classification;
- entity extraction;
- duplicate detection;
- reconciliation;
- export generation.

Capability rules:

- Capabilities return evidence, candidates, scores, or generated artifacts.
- Capabilities do not make business decisions.
- Capabilities should be reusable across business modules.
- Capabilities should be testable independently.
- Capabilities should log enough context for debugging and audit.

## 12. Dependency Rules

Preferred dependency direction:

```text
Business Module
  -> Workflow
  -> Policy
  -> Events
  -> Cognitive
  -> Knowledge
  -> Platform Core
```

Storage is used through models and repositories/selectors. External systems are accessed through integration services, not directly from business logic.

Allowed:

- Accounting calls policy services before approving or sending an invoice.
- Workflow emits events after status changes.
- Cognitive services read knowledge facts to improve suggestions.
- Learning services consume confirmed user corrections.

Forbidden:

- Accounting importing private document internals.
- Learning modifying workflow state directly.
- Cognitive services approving invoices directly.
- Policy rules calling external APIs directly.
- Django views containing matching or accounting logic.
- Models performing Merit, bank, EMTA, OCR, or LLM calls.

## 13. Coding Standards

Naming:

- Use explicit domain names.
- Prefer `DocumentIntakeService` over vague names such as `Helper`.
- Use consistent vocabulary from `MASTER_ARCHITECTURE.md`.

Type hints:

- Add type hints to new service functions and helper functions where practical.
- Prefer typed return objects or dictionaries with documented shapes for important results.

Docstrings:

- Add docstrings for non-obvious services, policies, validators, and capabilities.
- Do not add empty docstrings that restate the function name.

Logging:

- Log important operational failures.
- Do not log secrets, API keys, full bank data, or unnecessary personal data.
- Prefer structured event/audit records for business history.

Exceptions:

- Raise specific exceptions for expected business errors.
- Return validation results for user-correctable problems.
- Avoid broad `except` blocks that hide failures.

Configuration:

- Put organization-specific business settings in policies/configuration.
- Keep secrets out of Git.
- Use environment variables for runtime secrets.

## 14. Testing Strategy

Test layers:

- Unit tests: small functions, validators, selectors, policy rules.
- Integration tests: database behavior, services across apps, external client boundaries with fakes.
- Workflow tests: event chains, review tasks, status transitions, approvals.
- Regression tests: known invoice layouts, bank matching cases, Merit payloads, parsing edge cases.
- Architecture tests: dependency direction, forbidden imports, event emission expectations.

Minimum rule:

- Legacy tests must stay green.
- Django tests must stay green.
- New business rules need focused tests.
- Bug fixes should add regression tests when practical.

## 15. Review Checklist

Before every commit:

- Architecture respected.
- Tests green.
- No duplicated logic.
- No dead code.
- No hidden side effects.
- Documentation updated.
- No secrets or real business files committed.
- Events emitted for important changes.
- High-risk actions require confirmation.
- Commit has one clear purpose.

## 16. Git Workflow

Use small commits with meaningful messages.

Preferred workflow:

- Create a focused task.
- Make the smallest coherent change.
- Run tests.
- Review diff.
- Commit once.
- Push after the task or task group is ready.

Commit messages should describe the task and outcome, for example:

```text
TASK-003 add document engine foundation
EPIC-000 create engineering guide
```

Feature branches can be used when multiple people work in parallel or when a change is risky. Main branch should remain stable.

## 17. Future Evolution

Start as a modular monolith.

The Django platform should use strong internal module boundaries, services, events, policies, and capabilities before considering service extraction.

Microservices are allowed only if justified by real operational needs:

- separate scaling;
- separate deployment lifecycle;
- security boundary;
- external integration isolation;
- long-running processing requirements.

Architecture should allow future separation, but premature distribution would slow down learning and increase complexity.

## 18. Guiding Principles

Ten engineering commandments:

1. Business before technology.
2. Events are facts.
3. Knowledge is an asset.
4. Policy decides.
5. AI assists.
6. Every decision is explainable.
7. Every important action is auditable.
8. Small changes win.
9. Architecture evolves deliberately.
10. Build for the next decade.
