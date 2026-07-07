# Operations Workspace Platform Architecture

## 1. Vision

The product is the Operations Workspace Platform.

It is an enterprise platform where people perform daily operational work with assistance from AI. It is not an ERP, CRM, document archive, or e-mail client. It combines capabilities from those systems into one operational workspace where business context, evidence, decisions, workflows, and knowledge are visible together.

The vision:

- One Workspace.
- One Source of Truth.
- AI assisting every business process.
- Evidence before automation.
- Humans remain decision makers.

The platform should help teams move from scattered communication, files, tasks, accounting systems, and personal memory into one shared workspace where work can be understood, reviewed, acted on, and learned from.

## 2. Mission

The mission is to:

- reduce manual work
- reduce context switching
- reduce duplicated information
- increase decision quality
- create organizational memory

The platform should make daily operations faster without hiding important business decisions. It should reduce repetitive coordination, document handling, searching, copying, checking, and follow-up work while preserving human control.

## 3. Platform Principles

### Workspace Before Modules

Users should experience one workspace organized around operational work, not disconnected modules.

### Services Before UI

The UI must call domain services and platform engines. It should not bypass service-layer rules, workflow rules, policy decisions, or audit requirements.

### Knowledge Before AI

AI should use structured, verified, evidence-backed knowledge. The platform must build memory before asking AI to reason over it.

### Evidence Before Conclusions

Every suggestion, match, recommendation, or draft should be explainable through evidence.

### Explainability By Default

Users should see why the platform reached a conclusion. Explanations should be available in normal product screens, not only logs.

### Human Approval Before Automation

High-risk business actions require review and confirmation. AI suggests, workflow and policy decide, humans approve.

### Project-Centric Business Model

Projects are the primary business context for operational work. Communications, documents, tasks, workflows, decisions, and accounting often become meaningful through project context.

### Organization-Scoped Architecture

Organization is the tenant root. Data, permissions, configuration, policies, knowledge, and integrations are scoped by Organization.

### Read Models Separate From Write Models

Operational screens may need fast, denormalized, search-oriented read models. Business changes should still go through domain services, workflow, policy, and audit.

### Immutable Audit History

Important human and system actions are recorded as append-only audit history.

## 4. Platform Layers

```text
User Workspace
  -> AI / Cognitive Layer
  -> Knowledge Layer
  -> Business Engines
  -> Domain Models
  -> Infrastructure
```

### User Workspace

The user-facing workspace where people see tasks, projects, inboxes, reviews, documents, dashboards, search, and AI assistance.

Responsibilities:

- show work that needs attention
- explain suggestions
- collect user decisions
- support role-specific workflows
- make evidence visible

### AI / Cognitive Layer

The layer that supports OCR, extraction, validation, reasoning, prompt management, confidence scoring, and recommendations.

Responsibilities:

- produce suggestions and drafts
- work from controlled context
- expose uncertainty
- avoid direct hidden business changes

### Knowledge Layer

The memory layer that assembles communications, documents, workflow, audit, decisions, and future accounting outcomes into reusable business context.

Responsibilities:

- build knowledge DTOs
- provide evidence
- build timelines
- provide AI context
- support future search and retrieval

### Business Engines

Reusable business capabilities that coordinate workflows in specific domains.

Responsibilities:

- implement business rules through services
- orchestrate domain work
- call workflow, policy, audit, knowledge, and integrations
- remain testable outside the UI

### Domain Models

The persistent business objects such as Organization, Project, Document, EmailMessage, WorkflowInstance, AuditEvent, and future accounting objects.

Responsibilities:

- store core state
- enforce basic integrity
- remain thin where possible

### Infrastructure

Databases, storage, queues, integrations, authentication, background processing, deployment, and monitoring.

Responsibilities:

- provide reliable technical foundation
- support scaling
- secure secrets and data
- keep business services independent from vendor-specific details where practical

## 5. Business Engines

### Communication Engine

Imports, stores, processes, classifies, and links communications.

Responsibilities:

- e-mail account sync
- message import
- thread context
- question detection
- attachment-to-document conversion
- project link suggestions
- answer draft lifecycle

### Project Engine

Manages project context as the core operational memory container.

Responsibilities:

- project identity
- project parties
- project addresses
- future phases, tasks, decisions, risks, and project health

### Document Engine

Handles files as business documents, not only storage blobs.

Responsibilities:

- document identity
- document versions
- file fingerprinting
- document workflow start
- document status changes
- future OCR and parsing integration

### Workflow Engine

Controls generic workflow execution.

Responsibilities:

- workflow definitions
- workflow instances
- transitions
- workflow events
- traceable process history

### Knowledge Engine

Builds reusable organizational memory.

Responsibilities:

- project knowledge
- conversation context
- evidence aggregation
- timeline building
- controlled AI context
- future snapshots and search

### Policy Engine (Future)

Decides what actions are allowed, denied, or require review.

Responsibilities:

- risk rules
- approval policies
- amount thresholds
- supplier trust policies
- permission-aware automation

### Learning Engine (Future)

Learns from confirmed decisions and corrections.

Responsibilities:

- correction history
- learning rule candidates
- supplier memory
- project assignment memory
- account assignment memory

### Cognitive Engine (Future)

Coordinates AI and non-AI reasoning capabilities.

Responsibilities:

- OCR
- extraction
- validation
- confidence scoring
- prompt orchestration
- business reasoning

### Integration Engine (Future)

Connects external systems without leaking vendor logic into business services.

Responsibilities:

- Merit
- banks
- EMTA
- Microsoft 365
- file storage systems
- future REST APIs

### Accounting Engine (Future)

Coordinates accounting workflows inside the Operations Workspace.

Responsibilities:

- purchase invoice lifecycle
- invoice lines
- VAT treatment
- payment matching
- Merit sync
- EMTA export preview

### Scheduling Engine (Future)

Coordinates tasks, field work, reminders, capacity, and planned operational activities.

Responsibilities:

- task scheduling
- field work plans
- reminders
- resource planning
- calendar integration

## 6. Workspace Areas

### Dashboard

Shows attention, risk, recent activity, sync health, and review workload.

### Inbox

Shows imported communication with business interpretation, project suggestions, detected questions, attachments, workflow status, and suggested actions.

### Projects

The main operational workspace for project state, timeline, communication, documents, tasks, people, decisions, accounting, and AI context.

### Documents

Shows document previews, extracted fields, versions, related e-mails, related projects, workflow status, and audit trail.

### Reviews

Unified queue for confirmations, approvals, exceptions, AI drafts, duplicate warnings, field extraction review, and policy exceptions.

### Tasks

Operational task list for office users, project managers, site managers, and field workers.

### Search

Cross-domain search across projects, e-mails, documents, decisions, tasks, invoices, parties, and knowledge.

### AI Assistant

Context-aware assistant that helps inside projects, e-mails, documents, reviews, and global search.

### Administration

Settings, integrations, users, organization configuration, policies, and technical administration.

Users should move between areas through business context. For example, an Inbox item can lead to a project, document, task, review, or AI draft. A project can lead to related e-mails, documents, invoices, tasks, and decisions.

## 7. Operational Flow

Typical flow:

```text
Incoming Email
-> Communication Engine
-> Project Detection
-> Knowledge
-> Workflow
-> AI Recommendation
-> Human Review
-> Business Action
-> Audit
-> Learning
```

This flow turns incoming communication into structured work. The goal is not only to store an e-mail. The goal is to understand what it means, connect it to project context, route it through workflow, support the user with evidence-backed recommendations, record decisions, and improve future work.

## 8. Human + AI Collaboration

The collaboration philosophy:

- AI suggests.
- Humans confirm.
- Evidence is always shown.
- Corrections become learning.
- No hidden reasoning.

AI should reduce thinking load, not remove accountability. When AI drafts an answer, suggests a project, extracts invoice fields, matches a payment, or identifies missing documents, the user should see sources and uncertainty.

AI output becomes trusted platform knowledge only through confirmation, validation, or policy-approved processes.

## 9. Organization Memory

Every project contributes to organizational knowledge.

The platform should remember:

- confirmed project links
- supplier and customer patterns
- recurring document behavior
- workflow outcomes
- approved exceptions
- previous decisions
- user corrections
- communication history
- accounting outcomes

Knowledge is reusable. Past decisions improve future work. AI should use verified knowledge, not random unstructured context.

## 10. Workspace Philosophy

The platform is a workspace because real operational work does not fit cleanly into isolated systems.

In daily work, a single business question may involve:

- e-mail
- attachments
- project status
- contracts
- drawings
- task history
- invoice status
- payment status
- previous decisions
- workflow state
- AI summary

Traditional systems separate these into different tools. The Operations Workspace Platform brings them together inside one business context.

Example:

An e-mail arrives with an invoice and a question. The platform can show the message, thread, project, documents, detected questions, invoice status, payment match, evidence, AI draft answer, and review actions together.

## 11. Explainability

Every AI recommendation should be traceable to:

- evidence
- documents
- e-mails
- workflow
- user confirmations
- policies

There should be no black-box automation. A user should be able to understand:

- what was suggested
- why it was suggested
- what evidence supports it
- what uncertainty remains
- what action will happen if they approve it

Explainability is a product feature, not only a technical logging concern.

## 12. Scalability

The platform should grow in stages:

```text
Single company
-> Multiple companies
-> Multi-tenant SaaS
-> Industry platform
```

The architecture must support Organization-scoped data, future tenant isolation, role permissions, integration accounts, and scalable background processing.

The first implementation can remain local and simple, but the domain model, services, audit trail, and organization scope should avoid blocking future SaaS growth.

## 13. Future Vision

Future modules and capabilities may include:

- voice assistant
- BIM assistant
- procurement
- inventory
- scheduling
- OCR
- mobile
- field work
- predictive analytics
- autonomous workflows with approval

The platform should support these through shared engines, shared knowledge, shared policy, and shared workspace patterns rather than isolated one-off modules.

## 14. Product Roadmap

High-level evolution:

```text
Foundation
-> Business Engines
-> Knowledge
-> Workspace
-> AI Assistance
-> Learning
-> Enterprise Platform
```

Foundation establishes repository structure, Django platform, core Organization, audit, services, documents, workflow, communication, projects, and knowledge.

Business Engines turn domain objects into usable workflows.

Knowledge creates memory and controlled AI context.

Workspace makes the platform useful for daily work.

AI Assistance reduces manual work through evidence-backed suggestions and drafts.

Learning improves future recommendations from confirmed decisions.

Enterprise Platform scales the system across organizations, integrations, industries, and advanced operations.

## 15. Non-goals

The platform is not trying to replace:

- office suite
- CAD software
- accounting software
- e-mail providers

Instead, it orchestrates them.

The platform should connect business context, decisions, workflows, evidence, and AI assistance across external tools. It should not rebuild every specialist tool from scratch.

## 16. Why This Architecture

This architecture is:

- business-first
- AI-ready
- modular
- explainable
- auditable
- scalable
- future-proof

It starts from real operational work instead of database tables. It keeps humans in control while letting AI assist every process. It turns documents, communication, workflow, and decisions into organizational memory. It separates workspace, engines, knowledge, domain models, and infrastructure so each layer can grow without collapsing into a single fragile application.
