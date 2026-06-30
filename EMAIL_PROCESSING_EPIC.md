# Email Processing Epic

This epic describes the complete end-to-end lifecycle of an incoming business e-mail.

It follows `MASTER_ARCHITECTURE.md`, `ENTERPRISE_DOMAIN_MAP.md`, `COMMUNICATION_ARCHITECTURE.md`, `PROJECT_ARCHITECTURE.md`, and `ENGINEERING_GUIDE.md`.

## 1. Business Goal

Incoming e-mail should become structured organizational knowledge, not just a message in someone's mailbox.

An incoming business e-mail may contain a question, an invoice, an offer, a contract, a drawing, a project update, a meeting request, or a decision trail. The platform should preserve the original message, understand its context, connect it to projects and parties, process important attachments, support human review, and turn confirmed outcomes into business memory.

The goal is not only to import e-mail. The goal is to make e-mail part of the organization's usable memory.

## 2. Happy Path Overview

Complete flow:

Email arrives

-> Import

-> Classification

-> Project suggestion

-> User confirmation

-> Attachment extraction

-> Document creation

-> Workflow creation

-> OCR

-> Data extraction

-> Validation

-> Invoice candidate

-> Human review

-> Accounting export

-> Learning

-> Business Memory

This happy path is the reference flow for future implementation. Individual modules should be built in small steps, but the product should be judged by whether this full business scenario eventually works end to end.

## 3. Step 1 - Import

The platform receives or discovers an incoming e-mail through mailbox polling, webhook delivery, or imported mailbox data.

Import should capture:

- mailbox source;
- account;
- message id;
- thread id;
- sender;
- recipients;
- subject;
- body text;
- body html;
- sent and received timestamps;
- metadata;
- attachments.

Deduplication is required. The same e-mail may appear through multiple imports, mailbox folders, forwarded copies, or repeated sync attempts. Message id, thread id, timestamps, sender, subject, and content fingerprints should help prevent duplicates.

The import step should preserve raw evidence before interpretation begins.

## 4. Step 2 - Classification

The platform classifies the e-mail so the correct review and processing path can be suggested.

Possible classifications:

- purchase invoice;
- customer invoice;
- offer;
- contract;
- project communication;
- technical drawing;
- BIM;
- meeting;
- unknown.

Classification should be explainable. The platform should show whether the classification came from subject text, sender history, attachment names, document content, previous confirmations, or other evidence.

Unknown is a valid result. It is better to ask for review than to silently guess.

## 5. Step 3 - Project Suggestion

The platform suggests the project or projects that the e-mail may belong to.

Evidence sources:

- sender;
- recipients;
- subject;
- body;
- thread history;
- attachments;
- supplier history;
- customer history;
- previous confirmations.

The platform should provide:

- suggested project;
- confidence;
- reasoning.

Example:

Suggested project: Kanarbiku

Reasoning:

- sender has previously communicated about Kanarbiku;
- the e-mail thread was already linked to Kanarbiku;
- the attachment filename contains a known project reference;
- similar invoices from this supplier were previously confirmed for Kanarbiku.

## 6. Step 4 - User Confirmation

The user reviews the project suggestion.

The user may:

- accept;
- change project;
- create new project;
- postpone.

Confirmed decisions become learning data. Corrections are especially valuable because they teach the platform which evidence was misleading and which project context was correct.

The platform should remember both the suggested value and the final user-confirmed value.

## 7. Step 5 - Attachment Processing

Important attachments become Documents.

Relationship preserved:

EmailMessage

-> EmailAttachment

-> Document

-> DocumentVersion

The original e-mail remains communication evidence. The attachment remains evidence that a file arrived with that e-mail. The Document becomes the business identity for the file and future processing.

Not every attachment must become a high-priority business document, but important attachments such as invoices, contracts, drawings, BIM/IFC files, offers, bank statements, and specifications should.

## 8. Step 6 - Workflow

Document starts Workflow.

Workflow controls processing. It records where the document is in the business process and what happened during processing.

Possible workflow stages may include:

- received;
- classified;
- waiting for project confirmation;
- document created;
- OCR pending;
- extraction pending;
- validation pending;
- needs human review;
- approved;
- exported;
- archived;
- error.

Document status and workflow state are related but not identical. Document status is a summary. Workflow state is process execution.

## 9. Step 7 - AI Processing

Possible engines:

- OCR;
- Classification;
- Extraction;
- Validation;
- Knowledge lookup;
- Risk detection.

AI processing should produce evidence, candidates, scores, and explanations. It should not silently make high-risk business decisions.

For an invoice attachment, AI processing may extract supplier name, invoice number, invoice date, due date, total amount, VAT amount, IBAN, project references, and line descriptions.

For a project communication, AI processing may identify questions, requested actions, commitments, deadlines, and related documents.

## 10. Step 8 - Human Review

The user reviews:

- extracted fields;
- confidence;
- suggested project;
- accounting data.

Human review should focus attention where risk or uncertainty is highest. Low-confidence fields, new suppliers, changed bank details, duplicate risk, missing project, unusual VAT, or accounting validation failures should be visible.

The user may confirm, correct, reject, postpone, or request more information.

## 11. Step 9 - Accounting

Approved accounting-relevant data may be exported to:

- Merit;
- future ERP;
- future accounting systems.

Accounting export should be explicit, auditable, and traceable back to the original e-mail, attachment, Document, extraction evidence, review decision, and workflow history.

The platform should preserve both the outgoing accounting payload and the result of the external system interaction.

## 12. Step 10 - Learning

The system learns from:

- confirmed project;
- corrected extraction;
- corrected supplier;
- corrected invoice fields;
- accepted AI answer.

Learning should be based on confirmed user decisions, not unverified AI guesses.

Examples of learning:

- this sender usually belongs to this project;
- this supplier's invoices usually use this line format;
- this attachment naming pattern identifies a project;
- this VAT interpretation was corrected by the user;
- this type of question can be answered from project documents.

## 13. Step 11 - Business Memory

The platform stores:

- original email;
- attachments;
- workflow;
- AI reasoning;
- user corrections;
- accounting outcome.

Business Memory should preserve why something happened, not only what happened.

For example, the platform should remember that an invoice arrived by e-mail, was linked to a project, had extracted fields corrected by a user, was approved, exported to accounting, later matched to payment, and created learning rules for future similar invoices.

## 14. AI Explainability

Every AI decision should include:

- confidence;
- evidence;
- uncertainty;
- alternative candidates.

Examples:

- why this e-mail was classified as a purchase invoice;
- why this project was suggested;
- why this supplier was detected;
- why this invoice may be a duplicate;
- why this answer draft was proposed;
- which evidence was missing.

Explainability is required for trust, audit, learning, and correction.

## 15. Failure Scenarios

Common failure scenarios:

- OCR failed;
- no project found;
- low confidence;
- unknown supplier;
- duplicate invoice;
- accounting validation failed.

Failure should not lose the original e-mail or attachment. The platform should preserve the record, mark the issue, explain what failed, and route the item to review where needed.

Examples:

- If OCR fails, the Document remains stored and can be reviewed manually.
- If no project is found, the user can choose or create a project.
- If supplier is unknown, the user can confirm a new Party or supplier role later.
- If duplicate invoice risk exists, the platform should show evidence before blocking or allowing processing.
- If accounting validation fails, the item should remain reviewable with the validation result attached.

## 16. Future Automation

Possible future automation:

- automatic approvals;
- supplier-specific workflows;
- reminder generation;
- meeting creation;
- task creation;
- project health updates;
- risk prediction.

Automation must remain policy-driven and confidence-aware. High-risk actions should require human confirmation. The platform should automate repetitive preparation and evidence gathering before it automates final business decisions.

## 17. Relationship To Architecture

This epic connects these architecture documents:

- `MASTER_ARCHITECTURE.md`
- `COMMUNICATION_ARCHITECTURE.md`
- `PROJECT_ARCHITECTURE.md`
- `ENTERPRISE_DOMAIN_MAP.md`
- `ENGINEERING_GUIDE.md`

`EMAIL_PROCESSING_EPIC.md` is a scenario-level reference. It shows how communication, documents, workflow, cognitive processing, accounting, learning, and business memory should work together in one end-to-end business flow.
