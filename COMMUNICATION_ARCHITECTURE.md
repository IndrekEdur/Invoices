# Communication Architecture

This document defines how the platform will store, analyze, link, and use business communication as part of organization memory.

It follows `MASTER_ARCHITECTURE.md`, `ENTERPRISE_DOMAIN_MAP.md`, and `ENGINEERING_GUIDE.md`.

## 1. Vision

Communication is not only an integration.

Communication is a first-class business domain. E-mails, meetings, calls, chats, and AI conversations are part of organization memory.

The platform should not treat e-mail as a temporary transport mechanism where important context disappears after an attachment is extracted. The message, thread, participants, attachments, questions, decisions, and follow-up actions all matter.

The goal is to let the organization remember:

- who communicated;
- what was said;
- what project or party the communication related to;
- what questions or tasks came from it;
- what documents were attached;
- what answer was drafted or sent;
- what the user confirmed or corrected;
- what the platform learned from that confirmation.

## 2. Core Concepts

### Conversation

A broad communication context that may span multiple channels. It can contain e-mail threads, meetings, calls, chats, and future communication types.

### EmailAccount

An account that the platform can import e-mail from or prepare outgoing drafts for. It belongs to an Organization and may contain multiple mailboxes.

### Mailbox

A folder or mailbox area inside an e-mail account, such as inbox, sent, archive, project folders, or imported PST folders.

### EmailThread

An e-mail-specific thread that groups related EmailMessage objects by provider thread id, subject structure, references, or other message headers.

### EmailMessage

A single e-mail message with sender, recipients, subject, body, timing, direction, metadata, attachments, and links to projects or other business objects.

### EmailAttachment

A file attached to an EmailMessage. Important attachments become Document objects, while the original attachment relationship is preserved.

### EmailParticipant

A sender, recipient, copied person, or hidden recipient. Participants may later be linked to Party records.

### CommunicationChannel

The channel where communication happened, such as e-mail, meeting, phone call, chat, AI conversation, or future channels.

### CommunicationClassification

A classification result or user-confirmed label for communication, such as invoice-related, project question, offer request, contract discussion, support issue, or general information.

### ProjectCommunicationLink

A proposed or confirmed relationship between a communication object and a Project. It should keep confidence, evidence, user decision, and correction history.

### CommunicationQuestion

A detected question or action request inside communication. It may need an answer, task, workflow, or human review.

### CommunicationAnswerDraft

A proposed response created from related context. It must store the original question, used evidence, generated answer, user edits, approval status, and final sent text.

## 3. Conversation

Conversation is broader than EmailThread.

An EmailThread is only one e-mail-specific grouping. A real business conversation may include:

- e-mail;
- meeting;
- phone call;
- Teams, Slack, or WhatsApp chat;
- AI conversation;
- future communication channels.

The platform should allow these objects to be connected into a broader Conversation when they represent the same business matter.

For example, a project issue may begin as an e-mail, continue in a meeting, receive photos by chat, create a task, and end with a confirmed answer. The organization should see this as one connected conversation, not as disconnected fragments.

## 4. Email Domain

EmailMessage should store:

- organization;
- account;
- mailbox;
- external message id;
- thread id;
- subject;
- body text;
- body html;
- sender;
- recipients;
- cc;
- bcc;
- sent_at;
- received_at;
- direction;
- metadata.

Direction should distinguish inbound and outbound communication.

The platform should preserve original provider identifiers and metadata so later imports can avoid duplicates, reconstruct threads, and explain where a message came from.

## 5. Email Attachments And Documents

EmailAttachment belongs to EmailMessage.

Important attachments become Document objects. The attachment-to-document relationship must be preserved.

Document remains the business file identity. EmailAttachment records the fact that a file arrived with a specific e-mail. Document records the broader business identity of that file: source, status, versions, checksum, project links, workflows, and later processing.

This distinction allows the same Document to be understood in business context while preserving the original communication evidence.

## 6. Project Linking

The platform should suggest project links using evidence such as:

- project code in subject or body;
- sender history;
- thread history;
- attachment names;
- document contents;
- previous user confirmations;
- supplier, customer, and project relationships;
- related invoices, offers, and contracts.

The system must show:

- suggested project;
- confidence score;
- evidence;
- user confirmation or correction.

Project linking must be explainable. The user should be able to see why a project was suggested before accepting or correcting it.

## 7. Learning From Confirmed Links

The system learns only from confirmed user decisions.

Confirmed links may create:

- project sender patterns;
- thread/project memory;
- subject keyword patterns;
- document filename patterns;
- party/project relationship memory.

Unverified guesses must not become permanent learning rules. A suggestion becomes reusable knowledge only after a user confirms it or after repeated confirmed behavior establishes a trusted pattern.

## 8. Question Detection

The platform should detect when an e-mail asks a question or requests action.

Examples:

- "Kas see arve on kinnitatud?"
- "Millal too valmis saab?"
- "Kas saame pakkumise tanaseks?"
- "Mis projekti alla see kulu laheb?"

Question detection should identify the requested information or action, the likely project or party context, urgency if visible, and whether the question can be answered from existing business memory.

## 9. Project Context Answering

To answer a question, the platform should search:

- same project e-mails;
- related documents;
- decisions;
- tasks;
- invoices;
- offers;
- contracts;
- workflow events;
- project memory.

The platform must return:

- proposed answer;
- supporting evidence;
- uncertainty level;
- missing information, if any.

If the available context is weak or conflicting, the platform should explain the uncertainty instead of producing a confident answer.

## 10. Reply Drafts

AI drafts a response. A human approves before sending.

A CommunicationAnswerDraft must store:

- original e-mail;
- project context used;
- evidence used;
- generated answer;
- user edits;
- final approved text;
- sent status.

The draft should remain traceable after sending. Later users should be able to see what question was answered, what evidence was used, what the AI proposed, what the user changed, and what was finally sent.

## 11. Explainability

Every suggestion must explain why.

The platform should answer:

- why this project?
- why this answer?
- what evidence was used?
- what is uncertain?

Explainability is part of trust. Users should not have to accept a black-box project link, answer draft, or classification.

## 12. Workflows

Communication objects may have workflows.

Possible workflow states include:

- received;
- classified;
- linked_to_project;
- needs_review;
- answer_drafted;
- approved;
- sent;
- archived.

Workflow state is process execution state. Communication objects may also have their own summary status or classification, but these concepts must remain separate.

## 13. Events

Possible future events include:

- EmailImported
- EmailClassified
- EmailLinkedToProjectSuggested
- EmailLinkedToProjectConfirmed
- EmailQuestionDetected
- CommunicationAnswerDrafted
- CommunicationAnswerApproved
- CommunicationAnswerSent
- CommunicationLearningRuleCreated

Events should support audit, learning, debugging, progress views, and future automation.

## 14. Security And Privacy

E-mails may contain sensitive data.

Access must be organization-scoped. Project-based access rules may be needed when different users should see different communication contexts.

AI must not expose unrelated project context. If a user asks about one project, answer generation must not silently include sensitive information from another unrelated project.

Outbound e-mails require human confirmation. The platform may draft, suggest, classify, and explain, but sending business communication must remain a user-approved action.

## 15. Relationship To Existing Domains

### Organization

Communication belongs inside an Organization context.

### Project

Communication may be linked to Projects. Project context is essential for answering questions and preserving business memory.

### Party

Senders, recipients, customers, suppliers, employees, banks, authorities, and partners may be linked to Party records.

### Document

Important attachments become Documents. The original attachment relationship remains part of communication evidence.

### Workflow

Communication objects may move through workflows for classification, review, answer drafting, approval, sending, and archiving.

### Knowledge

Confirmed communication links, repeated patterns, user corrections, and approved answers can become business knowledge.

### Accounting

E-mails may contain invoices, payment questions, supplier correspondence, offers, contracts, or accounting context. Communication should provide evidence for accounting workflows without becoming accounting itself.

### Cognitive Layer

The Cognitive Layer helps classify messages, detect questions, suggest project links, draft answers, and explain evidence.

### Policy Layer

Policy decides what is allowed, what requires review, and what cannot happen automatically. Outbound communication and sensitive context use must respect policy.

## 16. MVP Path

Recommended implementation phases:

1. COMM-001 EmailAccount model
2. COMM-002 EmailMessage / EmailThread model
3. COMM-003 EmailAttachment -> Document integration
4. COMM-004 Project linking suggestions
5. COMM-005 User confirmation flow
6. COMM-006 Question detection
7. COMM-007 Reply draft engine
8. COMM-008 Search across project context

The MVP should begin with durable storage and traceable identity before adding intelligence. E-mail import, message identity, thread identity, and attachment-to-document links should come before project suggestion and answer drafting.
