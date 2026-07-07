# Platform UX Architecture

## 1. Vision

The platform user interface should turn communications, documents, projects, workflows, knowledge, and AI into one usable business workspace.

The platform is not just an admin panel. It must become a day-to-day workspace for project managers, site managers, electricians, accounting users, office administrators, and company management.

The interface should help users:

- see what needs attention
- confirm AI suggestions
- review documents
- answer e-mails
- understand project status
- trust evidence
- act quickly

The UI should make complex business context feel manageable. Users should not need to understand database tables, internal events, or integration payloads to make good decisions.

## 2. UX Principles

- Business-first, not database-first.
- Users see tasks and decisions, not raw tables.
- AI suggestions must be explainable.
- Every important action should show evidence.
- Review before automation.
- Role-specific views should prioritize each user's daily work.
- Minimal friction for common confirmations and corrections.
- Fast search across projects, communication, documents, and knowledge.
- Mobile-friendly workflows for site users.
- No normal user should need Django Admin.

The interface must support trust. If the system proposes a project, supplier, payment match, answer draft, or accounting action, the user should see why.

## 3. Primary User Roles

### Company Owner / Management

Needs:

- overview of project health
- financial and operational risk signals
- important decisions and approvals
- visibility into overdue tasks and unresolved questions
- confidence that automation is controlled and auditable

### Project Manager

Needs:

- project workspace with timeline, documents, people, decisions, and tasks
- e-mails linked to projects
- open questions and missing approvals
- document and invoice status
- AI summaries and evidence-backed recommendations

### Site Manager

Needs:

- mobile access to current project state
- tasks, messages, drawings, documents, and photos
- quick approvals and confirmations
- simple way to flag missing information or problems

### Electrician

Needs:

- mobile-first project tasks and documents
- latest drawings, work instructions, and messages
- simple photo/document upload
- clear status of assigned work

### Accounting User

Needs:

- invoice review and approval queue
- extracted fields with evidence
- payment matching status
- Merit/EMTA integration status
- exceptions, duplicates, VAT issues, and audit trail

### Office Administrator

Needs:

- inbox triage
- project and document confirmation
- missing document follow-up
- communication and workflow status
- simple way to assign tasks or ask for review

### Future External Collaborator

Needs:

- limited, permission-controlled access
- project-specific documents, tasks, messages, or approvals
- no visibility into internal accounting or unrelated projects

## 4. Main Navigation

Proposed main sections:

- Dashboard
- Inbox
- Projects
- Documents
- Tasks
- Reviews
- Accounting
- Search
- AI Assistant
- Settings

Navigation should be role-aware. Accounting users may see Accounting and Reviews first. Site users may see Projects, Tasks, and Documents first. Management may start from Dashboard and Search.

## 5. Dashboard

The dashboard should summarize attention, risk, and recent change.

Widgets:

- new e-mails
- e-mails needing project confirmation
- questions needing answers
- documents needing review
- invoices needing approval
- overdue tasks
- project risks
- recent AI suggestions
- sync health

Dashboard cards should lead directly to action queues, not only reports.

## 6. Inbox

The Inbox is not just an e-mail client.

It should show imported e-mails with business interpretation:

- detected project
- confidence
- evidence
- detected questions
- attachments
- workflow status
- suggested actions

Actions:

- confirm project
- change project
- create new project
- dismiss
- create task
- create document
- draft reply

The Inbox should help users convert communication into structured business memory.

## 7. Email Detail View

The Email Detail View should include:

- message body
- thread context
- sender and recipients
- project suggestion
- evidence
- questions detected
- attachments
- related documents
- AI draft reply
- approval controls
- audit trail

The user should be able to inspect the original e-mail and the platform's interpretation side by side.

## 8. Project Workspace

The Project Workspace is the most important workspace.

Tabs:

- Overview
- Timeline
- Communications
- Documents
- Tasks
- Decisions
- Invoices
- Offers
- Drawings / BIM
- People
- AI Assistant
- Knowledge

Project Workspace should combine business context that would otherwise be scattered across e-mail, folders, accounting software, spreadsheets, chat, and people's memory.

## 9. Project Overview

The Project Overview should show:

- current project state
- recent events
- open questions
- missing documents
- pending approvals
- risks
- latest e-mails
- latest documents
- AI summary

The overview should answer: what is happening, what needs attention, and what changed recently?

## 10. Timeline

The timeline should combine:

- e-mails
- document events
- workflow events
- decisions
- tasks
- meetings
- accounting events
- AI summaries

Timeline entries should link back to source objects and evidence. Users should be able to filter by type and inspect the full context.

## 11. Reviews / Approval Queue

The platform should provide one unified review queue for:

- project link confirmations
- extracted invoice fields
- AI answer drafts
- document classifications
- duplicate warnings
- policy exceptions
- accounting approvals

Review cards should show the proposed action, confidence, evidence, source object, and available decisions.

## 12. Evidence View

Every AI or rule-based suggestion should show:

- evidence list
- source object
- matched value
- confidence
- reason
- user confirmation status

Evidence should be inspectable without opening developer tools or raw JSON. Users should understand why the platform is asking them to confirm or approve something.

## 13. Document Workspace

The Document Workspace should include:

- document preview
- extracted fields
- workflow status
- related e-mail
- related project
- related invoice
- versions
- audit trail
- AI notes

Document review should be optimized for confirming, correcting, classifying, and approving.

## 14. AI Assistant Panel

The AI Assistant should be context-aware.

It can appear:

- globally
- inside project
- inside e-mail
- inside document
- inside review

It must:

- show sources
- show uncertainty
- create drafts, not send automatically
- ask for confirmation before risky actions

The AI Assistant supports the process. It does not become the process owner.

## 15. Search

Global search should cover:

- projects
- e-mails
- documents
- decisions
- tasks
- invoices
- parties
- knowledge

Search should support filtering by project, party, document type, date, source, and status.

Future search should include semantic search, but the first version should still return source-backed results with clear evidence and links.

## 16. Mobile UX

For site managers and electricians, mobile should support:

- project status
- tasks
- photos
- documents
- quick approvals
- messages
- AI summary

Mobile UX should prioritize speed, clarity, and low typing effort. It should not try to recreate the whole desktop workspace.

## 17. Permissions and Visibility

The UI must respect organization, project, and role permissions.

Users should only see allowed:

- projects
- e-mails
- documents
- accounting data
- AI context

Permission rules must apply to search results, AI context, evidence panels, dashboards, notifications, and exports.

## 18. Notifications

Notifications should support:

- new important e-mail
- question detected
- approval needed
- missing document
- overdue task
- sync failure
- AI draft ready

Notifications should lead to the relevant review, task, e-mail, document, or project context.

## 19. Technical UI Direction

Future technical direction:

- frontend as a separate app
- React / Next.js / TypeScript as likely option
- Django provides API and services
- UI should not bypass the service layer
- Django Admin remains a developer/admin tool only

The frontend should consume business-oriented endpoints and service results. It should not recreate domain logic, policy checks, evidence assembly, or workflow rules in browser code.

## 20. MVP UI Path

Recommended implementation phases:

1. `UI-001 Frontend skeleton`
2. `UI-002 Authentication shell`
3. `UI-003 Dashboard MVP`
4. `UI-004 Inbox MVP`
5. `UI-005 Email detail view`
6. `UI-006 Project workspace MVP`
7. `UI-007 Review queue`
8. `UI-008 AI assistant panel skeleton`
9. `UI-009 Document workspace MVP`

The MVP should prove that the platform works as a business workspace before building a large general-purpose ERP interface.

## 21. Non-goals

Do not implement immediately:

- full ERP UI
- full e-mail client
- full accounting UI
- mobile native app
- automatic AI actions without confirmation

The first UI should make existing business scenarios visible, reviewable, and trustworthy.
