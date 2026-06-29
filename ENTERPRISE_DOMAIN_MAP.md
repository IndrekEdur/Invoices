# Enterprise Domain Map

This document describes the business domain vision of the platform.

`MASTER_ARCHITECTURE.md` describes how the system is built.
`ENGINEERING_GUIDE.md` describes how software is developed.
`ENTERPRISE_DOMAIN_MAP.md` describes what the organization knows, remembers, communicates, and acts on.

## 1. Vision

The platform represents the complete digital memory of an organization.

Every important business activity should become a first-class business object. Nothing important should exist only inside someone's mailbox, computer, memory, phone, notebook, spreadsheet, or isolated software tool.

The platform should remember everything important so that people don't have to.

This does not mean replacing people. It means preserving context, evidence, relationships, decisions, and history so people can work with better memory, fewer missing details, and clearer reasoning.

## 2. Enterprise Domain Overview

The platform should understand the organization through these top-level business domains:

- Organization
- Parties
- Projects
- Communications
- Documents
- Workflows
- Accounting
- Decisions
- Tasks
- Calendar
- Knowledge
- AI / Cognitive Layer
- Integrations

These domains are connected. A project may contain documents, e-mails, meetings, invoices, payments, decisions, tasks, and knowledge. A party may be a customer in one context, a supplier in another, and a partner in a future project.

## 3. Organization

Organization is the tenant and root business context of the platform.

An Organization may represent a company, sole proprietor, non-profit, government body, or another entity that uses the platform to manage its business memory and operations.

All business information belongs inside an Organization context: documents, communications, projects, parties, workflows, accounting records, decisions, tasks, knowledge, and integrations.

## 4. Parties

Party represents any legal or natural person that may appear in business activity.

Examples:

- customer
- supplier
- employee
- consultant
- subcontractor
- authority
- bank
- partner

Supplier and Customer are roles of Party.

This separation matters because the same real-world person or company may appear in different roles over time. A company may be a supplier for one project and a partner in another. A person may be an employee, contact person, approver, consultant, or meeting participant depending on context.

## 5. Projects

Project is a central business context.

A project can have:

- documents
- e-mails
- conversations
- invoices
- payments
- decisions
- meetings
- tasks
- drawings
- BIM/IFC files
- AI summaries
- knowledge facts

Project context helps the platform connect related information that would otherwise be scattered across mailboxes, folders, accounting tools, and personal memory.

When a document, e-mail, invoice, meeting, or decision belongs to a project, the platform should preserve that link and explain why the link exists.

## 6. Communications

Communication is a first-class domain, not just an integration.

Communication objects include:

- Conversation
- EmailAccount
- Mailbox
- EmailThread
- EmailMessage
- EmailAttachment
- Meeting
- PhoneCallSummary
- ChatMessage
- AIConversation

E-mail is a communication object. An attachment is usually a Document. A thread is context. A conversation may span e-mail, Teams, phone calls, meetings, chat messages, and future channels.

The platform should remember not only individual messages, but also the larger conversation: who said what, when, in which context, and what decisions or tasks followed.

## 7. Email Intelligence

The platform should import e-mails and store them as EmailMessage objects.

For each e-mail, the platform should detect:

- sender
- recipients
- subject
- body
- attachments
- thread

The platform should suggest project links and explain why a project link was suggested. For example, the reason may come from the sender, subject, attachment name, project code, previous user confirmations, related documents, or repeated communication patterns.

The user should confirm or correct suggested project links. The platform should learn from confirmed project links, not from unverified guesses.

The platform should detect questions in e-mails. When a question is found, it should search project context for possible answers using related e-mails, documents, decisions, invoices, offers, and project memory.

The platform may draft an answer, but sending must require user confirmation. The final answer and its reasoning context should be stored so the organization remembers both the response and why it was given.

## 8. Documents

Document is a business identity, not just a file.

A file is stored content. A Document is the business object that gives the content identity, context, source, status, versions, relationships, and history.

Documents include:

- invoices
- contracts
- drawings
- BIM/IFC files
- photos
- videos
- specifications
- bank statements
- e-invoices
- exported reports

A Document may belong to a project, party, communication thread, workflow, decision, accounting process, or knowledge fact. The platform should preserve these relationships instead of treating files as isolated attachments.

## 9. Decisions

Decision is a first-class object.

A Decision should capture:

- what was decided
- who decided
- when
- why
- supporting evidence
- affected project, party, document, or workflow
- whether the decision was later changed

Example:

ABB selected for lighting because delivery time was shorter.

Decisions are important because they explain why the organization acted in a certain way. Without recorded decisions, future people may see only the result, not the reasoning.

## 10. Tasks

Tasks are actions that need to be done.

Tasks may be created from:

- e-mails
- meetings
- workflows
- decisions
- AI suggestions

A task should keep its source context. If a task came from an e-mail question, the platform should remember that e-mail. If a task came from a meeting decision, the platform should remember the meeting and decision.

## 11. Business Relationships

Important relationships include:

Project -> Documents
Project -> Conversations
Project -> Decisions
Project -> Tasks
Project -> Accounting Entries

Party -> Conversations
Party -> Documents
Party -> Contracts
Party -> Payments
Party -> Decisions

EmailMessage -> Attachments -> Documents
EmailMessage -> Project suggestion -> User confirmation -> Learning
Question in Email -> Project context -> Draft answer -> User confirmation

These relationships are part of the organization's memory. They help people answer practical questions such as:

- Which project is this invoice related to?
- Why did we choose this supplier?
- Which e-mail started this task?
- Has this question already been answered?
- Which documents support this decision?

## 12. Business Memory

Knowledge is created from:

- communications
- documents
- workflows
- meetings
- decisions
- accounting events
- AI observations
- user corrections

Business Memory should capture why something happened, not only what happened.

For example, it is useful to know that an invoice was approved. It is more useful to know why it was approved, which project it belonged to, what evidence supported it, whether there was an exception, and who confirmed it.

Business Memory should become stronger over time through confirmed corrections, repeated decisions, and trusted patterns.

## 13. AI Context Model

When AI helps answer a business question, it should:

- identify the current object
- identify project and party context
- search related e-mails
- search related documents
- search decisions
- search previous answers
- provide an answer with evidence
- create a draft, not automatically send

The platform should prefer evidence-based answers. If the answer is uncertain, it should say so and ask for confirmation.

AI should help people use the organization's memory, not invent business facts.

## 14. Non-Technical Principle

This document should remain understandable to non-programmers.

It describes the business world the platform should represent: organizations, people, projects, communications, documents, decisions, tasks, accounting context, knowledge, and memory.

Implementation details belong in technical architecture and engineering documents, not here.

## 15. Relationship To Other Documents

- `MASTER_ARCHITECTURE.md` = technical architecture
- `ENGINEERING_GUIDE.md` = engineering rules
- `ENTERPRISE_DOMAIN_MAP.md` = business domain map
