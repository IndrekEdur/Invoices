# Project Architecture

This document describes the Project Domain as the central business context of the platform.

It follows `MASTER_ARCHITECTURE.md`, `ENTERPRISE_DOMAIN_MAP.md`, `COMMUNICATION_ARCHITECTURE.md`, and `ENGINEERING_GUIDE.md`.

## 1. Vision

Projects are the primary business context of the platform.

A Project is not merely a construction project, a task list, or a folder. A Project is an organizational memory container that connects people, communications, documents, workflows, accounting, decisions, knowledge, and AI reasoning.

Almost every business object belongs to zero, one, or more projects. Some objects are general organization-level records, but many important records need project context to be understood correctly.

The platform should understand a project the same way an experienced project manager does: as a living context with history, relationships, open questions, risks, commitments, evidence, decisions, and next actions.

## 2. Core Concepts

### Project

The central business context that groups related activity, memory, and evidence.

### ProjectMember

A person or party participating in a project. A member may be internal or external and may have different responsibilities over time.

### ProjectRole

The role a member has in a project, such as client contact, project manager, supplier, subcontractor, designer, accountant, approver, or observer.

### ProjectPhase

A meaningful stage in the project lifecycle, such as lead, offer, planning, active work, delivery, warranty, archived, or cancelled.

### ProjectTimeline

The chronological history of important project activity: communications, workflow events, accounting events, meetings, tasks, document revisions, and decisions.

### ProjectKnowledge

Project-specific memory built from documents, communications, decisions, user corrections, repeated patterns, and approved summaries.

### ProjectDecision

A decision made in project context, including what was decided, who decided, why, when, and what evidence supported the decision.

### ProjectTask

A task or action connected to the project. It may come from communication, meetings, workflows, decisions, or AI suggestions.

### ProjectCommunication

E-mails, conversations, meetings, calls, chats, and answer drafts connected to the project.

### ProjectDocument

Documents connected to the project, including invoices, contracts, drawings, photos, BIM/IFC files, bank documents, reports, specifications, and correspondence attachments.

### ProjectWorkflow

Workflow instances that execute project-related processes, such as document review, approval, issue handling, offer preparation, or accounting review.

### ProjectAccounting

Accounting context connected to the project, including invoices, payments, costs, revenues, budgets, allocations, and accounting evidence.

## 3. Project Context

Project provides context for:

- documents;
- conversations;
- meetings;
- tasks;
- decisions;
- invoices;
- contracts;
- drawings;
- BIM/IFC;
- workflows;
- AI memory.

Without project context, the platform may know that an e-mail, invoice, or document exists, but not why it matters.

Project context helps people answer practical questions:

- Which project does this invoice belong to?
- Which communication explains this decision?
- Which documents support this offer?
- What is still unresolved?
- Who is responsible?
- What happened recently?

## 4. Project Memory

Project Memory is the accumulated business memory of a project.

Project Memory should accumulate:

- e-mails;
- conversations;
- documents;
- workflow history;
- decisions;
- meetings;
- invoices;
- contracts;
- supplier history;
- customer history;
- AI summaries;
- user corrections.

Project Memory should capture both what happened and why it happened. It should preserve evidence, user confirmations, corrections, and summaries so project understanding improves over time.

The platform should not rely on one person's memory or mailbox to understand a project. Important context should become shared organizational memory.

## 5. Project Timeline

The project timeline consists of:

- communications;
- workflow events;
- accounting events;
- meetings;
- tasks;
- document revisions;
- decisions.

The timeline should help users reconstruct the project story. It should show what happened, when, who was involved, which documents changed, which decisions were made, and which actions followed.

A good timeline is not only a log. It is a way to understand project progress, risk, missing actions, and context.

## 6. AI Understanding

AI should understand projects as living business contexts.

AI should identify:

- current project state;
- open questions;
- unresolved tasks;
- recent decisions;
- risks;
- missing documents;
- missing approvals;
- communication patterns.

AI should use project context to support people, not replace their judgment. It should explain what evidence it used and where uncertainty remains.

Useful project understanding examples:

- This supplier usually appears in this project.
- This invoice likely belongs to this project because the attachment and e-mail thread match.
- This project has several unanswered questions from the last week.
- This approval appears to be missing.
- This decision changed earlier project assumptions.

## 7. Project Linking

The platform should associate objects with projects using evidence.

Possible evidence includes:

- explicit project code;
- sender history;
- document metadata;
- workflow history;
- conversation history;
- supplier relationship;
- customer relationship;
- user confirmations.

Project linking should use confidence scoring and explainability.

A project link can be:

- proposed;
- confirmed;
- corrected;
- rejected;
- learned from confirmed behavior.

The system must not silently turn uncertain suggestions into permanent project memory. User confirmation and correction are important parts of learning.

## 8. Explainability

Every project suggestion must include evidence.

Example:

Suggested project:
Kanarbiku

Reasoning:

- sender belongs to project;
- thread belongs to project;
- attachment references project;
- supplier usually works on this project.

Explainability should show what the platform knows, what it is guessing, and what still needs confirmation.

## 9. Business Relationships

Project -> Documents

Project -> Conversations

Project -> Decisions

Project -> Tasks

Project -> Meetings

Project -> Accounting

Project -> Workflow

Project -> Knowledge

Project -> AI Memory

These relationships make Project the practical place where business context comes together.

## 10. Search

Searching a project should return:

- documents;
- conversations;
- meetings;
- decisions;
- tasks;
- invoices;
- contracts;
- workflows;
- AI summaries.

Search should not only find text. It should understand relationships. A project search should help the user move from a question to supporting evidence, related communication, decisions, and actions.

## 11. AI Question Answering

When asked about a project, AI should search:

- conversations;
- documents;
- decisions;
- workflows;
- accounting;
- meetings;
- previous AI answers.

AI should always provide:

- answer;
- supporting evidence;
- confidence;
- uncertainty.

If information is missing, AI should say what is missing. If evidence conflicts, AI should show the conflict. If the answer requires a business decision, AI should draft or suggest, not silently decide.

## 12. Future Capabilities

Future project capabilities may include:

- project health;
- risk prediction;
- missing document detection;
- automatic meeting summaries;
- automatic follow-ups;
- project timeline generation;
- semantic search;
- project chat assistant.

These capabilities should build on confirmed project memory, not isolated guesses.

## 13. Relationship To Other Documents

- `MASTER_ARCHITECTURE.md` describes the technical platform architecture.
- `ENTERPRISE_DOMAIN_MAP.md` describes the broader business domain map.
- `COMMUNICATION_ARCHITECTURE.md` describes communication as part of organization memory.
- `ENGINEERING_GUIDE.md` describes engineering rules for implementing the platform safely.
