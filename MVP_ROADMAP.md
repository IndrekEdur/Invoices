# Operations Workspace MVP Roadmap

## 1. MVP Vision

The MVP vision is simple:

A company employee opens one browser tab in the morning. Everything needed for daily operational work is available there.

No Outlook for daily triage. No Windows folders for finding documents. No searching across multiple systems to understand project history. No copying the same information between tools unless an external system still requires it.

One Workspace.

The MVP should be production-usable for a real installation company. It should not contain every future module, but it must cover a complete daily workflow: communication arrives, project context is identified, documents are accessible, reviews are handled, AI suggestions are checked, answers are drafted, and project history is searchable.

## 2. Success Criteria

The MVP is successful when users can reliably:

- receive e-mails
- automatically assign or suggest projects
- review AI and rule-based suggestions
- approve invoices or prepare them for accounting workflow
- open documents
- reply to e-mails using reviewed drafts
- search project history
- view project timeline
- understand evidence behind suggestions
- see what needs attention today
- work without switching constantly between Outlook, folders, spreadsheets, and accounting screens

Measurable goals:

- Most incoming business e-mails are visible in the platform.
- Most project-related e-mails receive a suggested project.
- Users can confirm or correct project suggestions in one review flow.
- Attachments can be opened from the related e-mail and project.
- Project timeline shows e-mails, documents, questions, reviews, and workflow events.
- Search returns e-mails, projects, documents, people, questions, and knowledge.
- AI drafts are never sent without user approval.
- Important user actions are audited.

## 3. Daily User Journey

### Project Manager

The project manager opens the Dashboard and sees pending project confirmations, questions from customers, recent project changes, and documents needing attention.

They open the Inbox, confirm project suggestions, review questions, open related project workspaces, check timelines, and approve or edit AI draft replies.

During the day, they use project search and AI summaries to answer customer questions without digging through e-mail history or folders.

### Office Administrator

The office administrator starts from the Inbox and Review Queue.

They classify incoming e-mails, confirm or correct suggested projects, check attachments, create or link documents, and assign items that need project manager or accounting review.

They use the platform to reduce loose e-mails and missing documents.

### Company Owner

The company owner starts from the Dashboard.

They see project risks, pending approvals, overdue questions, sync health, and today's important activity.

They do not need every low-level detail, but they need confidence that work is moving, exceptions are visible, and decisions are auditable.

### Site Manager

The site manager uses a simplified project workspace.

They open current projects, check tasks, messages, documents, and latest decisions. They can view project history and upload or review documents without searching through e-mail threads.

### Accounting User

The accounting user starts from Reviews and Accounting-related document queues.

They inspect invoices, extracted fields, related e-mails, project links, attachments, payment or accounting status, and audit trail. They approve or reject suggested data before anything is sent to accounting systems.

## 4. MVP Functional Areas

The MVP consists of these functional areas:

- Dashboard
- Inbox
- Projects
- Documents
- Review Queue
- Search
- AI Assistant
- Administration

Each area should support a complete business flow rather than exposing raw database tables.

## 5. Dashboard MVP

Dashboard widgets:

- new e-mails
- pending reviews
- questions detected
- AI drafts
- recent projects
- sync status
- today's activity

The Dashboard should answer: what needs attention today?

Each widget should link directly to the relevant Inbox, Review Queue, Project, Document, or Search view.

## 6. Inbox MVP

Capabilities:

- view imported e-mails
- open e-mail
- confirm project
- correct project
- view evidence
- open related project
- open attachments
- generate draft reply

The Inbox MVP should not try to become a full e-mail client. It should focus on turning incoming communication into project-linked, reviewable business work.

## 7. Project Workspace MVP

Tabs:

- Overview
- Timeline
- Emails
- Documents
- People
- Knowledge
- AI

The Project Workspace is the primary business context. A user should be able to understand a project's current status, recent history, documents, people, questions, and AI summary from one place.

## 8. Documents MVP

Document capabilities:

- preview
- versions
- related e-mail
- related project
- workflow state
- audit

Documents should be accessed through project and e-mail context, not only through a standalone file list.

## 9. Review Queue MVP

Unified queue for:

- project suggestions
- question detections
- AI drafts
- invoice extraction
- document classification
- future OCR

The Review Queue should show what is being proposed, why it is being proposed, what evidence supports it, and what action the user can take.

## 10. Search MVP

Global search for:

- e-mails
- projects
- documents
- people
- questions
- knowledge

Search results should include source object, related project, date, and enough context to decide whether the result is useful.

## 11. AI MVP

AI may:

- create draft replies
- summarize project
- summarize documents
- suggest project
- explain evidence

AI may not:

- send e-mails
- approve invoices
- modify accounting
- change workflow automatically

The AI MVP is assistant-first and approval-first. It should make daily work easier without creating hidden business changes.

## 12. Security MVP

The MVP must include:

- authentication
- organization isolation
- permissions
- audit

Security is not a later feature. Even the first production-usable version must protect organization data and restrict access to projects, documents, accounting information, and AI context.

## 13. Integrations

Initial integrations:

- IMAP
- PST Import

Future integrations:

- Microsoft 365
- Gmail
- Accounting
- OCR
- BIM
- Calendar

The MVP should start with the integrations needed to bring real communication and legacy mailbox data into the workspace.

## 14. MVP Milestones

### Phase A: Django HTMX Workspace

Create the first browser-based workspace using Django and HTMX.

Goal:

- authenticated shell
- navigation
- basic dashboard
- simple Inbox
- project workspace skeleton

### Phase B: Daily Internal Use

Make the platform usable by the internal team for real daily testing.

Goal:

- imported e-mails visible
- project suggestions reviewable
- documents linked
- review queue usable
- audit visible

### Phase C: Replace Outlook Workflow

Move daily e-mail triage from Outlook into the platform.

Goal:

- users can process incoming business e-mails
- confirm/correct projects
- open attachments
- draft replies
- track questions

### Phase D: Replace Document Folders

Make project and document search good enough that users stop relying on Windows folders for daily lookup.

Goal:

- project document lists
- document preview
- versions
- related e-mail
- related workflow state

### Phase E: AI-Assisted Operations

Add controlled AI assistance to daily work.

Goal:

- project summaries
- document summaries
- draft replies
- evidence explanations
- no automatic risky actions

## 15. Definition of Done

The MVP is done when a company can:

- receive e-mail
- find project
- find document
- answer customer
- track history
- review AI
- search everything

without leaving the platform for daily operational context.

External tools may still exist. Accounting software, e-mail providers, and file systems are not removed. But daily operational decisions should happen inside the Operations Workspace.

## 16. Future Beyond MVP

Future expansion:

- React Workspace
- Mobile
- Learning Engine
- Cognitive Engine
- Industry SaaS

The MVP should avoid blocking these future directions, but it should not try to implement all of them immediately.

## 17. Product Philosophy

The platform is not a collection of modules.

It is one operational workspace.

Every piece of information should exist once, be connected, explainable, and reusable.

The MVP should prove that this philosophy works in daily company operations before the platform expands into a larger enterprise system.
