# Knowledge Engine Architecture

## 1. Vision

The Knowledge Engine is the memory layer of the Cognitive Business Platform.

The platform should remember everything important so people do not have to. It should not only store files, e-mails, invoices, or workflow rows. It should preserve the relationships, evidence, decisions, confirmations, corrections, timelines, and context that explain why something is known.

Knowledge is not only extracted text. A sentence copied from an e-mail is data. A project link confirmed by a user, supported by sender history, attachment names, previous workflow events, and later accounting outcomes, is business knowledge.

The Knowledge Engine must make that knowledge reusable, explainable, auditable, and safe for future AI-assisted work.

## 2. Knowledge Layers

Knowledge exists at several scopes.

### Conversation Knowledge

Conversation Knowledge describes what is known from an e-mail message, thread, answer draft, question, attachment, and related documents.

It answers questions such as:

- What is this conversation about?
- Which project does it likely belong to?
- What questions were asked?
- What answers were drafted or approved?
- Which attachments became documents?
- What evidence supports the current interpretation?

### Project Knowledge

Project Knowledge describes the combined business memory of a project.

It joins communications, documents, parties, workflow history, decisions, audit trail, and future accounting objects into one explainable project context.

### Party Knowledge

Party Knowledge describes what the platform knows about a legal or natural person that appears in business activity.

Examples include suppliers, customers, subcontractors, consultants, banks, employees, and authorities. Party Knowledge may include known e-mail addresses, VAT numbers, registry codes, IBANs, project history, account assignment history, and confirmed exceptions.

### Organization Knowledge

Organization Knowledge describes tenant-wide memory.

Examples include trusted parties, organization policies, preferred accounting rules, common project code patterns, recurring document behavior, accepted exceptions, language preferences, and historical decisions.

## 3. Project Knowledge

`ProjectKnowledge` is a DTO/context object before it is a database model. Its first purpose is to gather structured context from existing domain objects without mutating them.

It may aggregate:

- `project`
- project parties
- project addresses
- related e-mails
- e-mail threads
- questions
- answer drafts
- attachments
- documents
- document versions
- workflow instances
- workflow events
- audit events
- decisions
- accounting objects in future
- evidence
- timeline
- metadata

The DTO should be suitable for:

- project overview screens
- AI context generation
- explainable project suggestions
- project search
- project timeline generation
- audit and debugging

`ProjectKnowledge` must not become a hidden place where business decisions are made. It reads and organizes context. Services, workflows, and policies decide what actions are allowed.

## 4. Evidence

Evidence is a first-class concept.

Every suggestion, match, draft, recommendation, or AI context item should be traceable to evidence. Evidence explains why the platform believes something.

Evidence should include:

- source type
- source id
- source label
- reason
- confidence
- extracted value
- matched value
- timestamp
- metadata

Examples:

- project code matched in e-mail subject
- sender previously confirmed for project
- attachment filename matched project
- document contained VAT number
- user confirmed project link
- workflow state changed

Evidence should be structured enough for machines to filter and rank, but readable enough for users to understand. A user should be able to inspect a recommendation and see what facts, documents, events, or confirmations support it.

Evidence confidence is not the same as final decision confidence. Policy, workflow state, amount thresholds, user permissions, and risk rules may still require human review.

## 5. Timeline

`ProjectTimeline` is a structured timeline of important project activity.

It should combine:

- e-mails
- workflow events
- document events
- decisions
- audit events
- questions
- answer drafts
- accounting events later

The timeline should be useful for both people and systems.

For people, it should explain what happened and when. For future AI and reasoning services, it should provide ordered context so recommendations are based on the sequence of events, not only isolated records.

Timeline entries should preserve source references and evidence. They should not flatten away the original domain object identity.

## 6. Knowledge Builders

Knowledge Builders are read-only services that assemble knowledge DTOs.

Planned builders:

- `ConversationContextBuilder`
- `ProjectKnowledgeBuilder`
- `PartyKnowledgeBuilder`
- `OrganizationKnowledgeBuilder`
- `EvidenceBuilder`
- `TimelineBuilder`

Builders should:

- read existing domain objects
- not mutate source objects
- not call AI directly
- return structured DTOs
- preserve evidence and source references
- be deterministic where practical

Builders are not workflow engines, policy engines, or AI agents. They prepare context. They do not approve invoices, send e-mails, change workflow states, mark payments, or create hidden business decisions.

## 7. Knowledge Snapshots

Knowledge Snapshots are frozen knowledge states.

They can later be stored for:

- audit
- AI reproducibility
- answer generation history
- compliance
- debugging

A snapshot should capture what the platform knew at the time a recommendation, answer draft, approval, or export was made.

This matters because knowledge changes. A project may gain new e-mails, a supplier may be corrected, a document may be reprocessed, or a user may reject an earlier suggestion. Historical decisions must remain explainable using the context available at the time.

## 8. AI Context Provider

AI should not query random tables directly.

AI should receive controlled context from the Knowledge Engine. This prevents inconsistent prompts, excessive data exposure, untraceable reasoning, and hidden coupling between AI code and domain tables.

Flow:

```text
Business object
-> Knowledge Builder
-> Evidence
-> Context
-> AI
-> Draft/Recommendation
-> Human confirmation
```

The AI Context Provider should:

- choose relevant context for the task
- include evidence and source references
- exclude unrelated or sensitive data
- preserve prompt reproducibility
- support human review
- log enough information for audit and debugging

AI output is not knowledge by default. AI output becomes reusable knowledge only after validation, confirmation, or another policy-approved process.

## 9. Search and Retrieval

Future search should support:

- keyword search
- semantic search
- project-scoped search
- party-scoped search
- document-scoped search
- evidence-aware retrieval

Search should not only return raw rows. It should return results with context and evidence.

Example result:

- matching document
- related project
- related party
- source e-mail thread
- relevant timeline entries
- confidence or ranking reason

Semantic search and embeddings are future capabilities. The first implementation should keep search simple and deterministic, then add richer retrieval once the domain model and evidence structures are stable.

## 10. Learning Relationship

The Knowledge Engine and Learning Engine are related but separate.

The Knowledge Engine stores what is known.

The Learning Engine consumes confirmed corrections and user decisions, then decides what patterns can be reused.

Examples:

- A user confirms an e-mail belongs to a project.
- The Knowledge Engine records the confirmed fact and evidence.
- The Learning Engine may later propose a rule that this sender often belongs to that project.
- The Policy Layer decides whether and when that rule can affect automation.

Learning must not be based on unverified AI guesses. Human-confirmed facts, repeated confirmed decisions, and audited outcomes are more trusted than suggestions.

## 11. Relationship to Existing Domains

### Communication

Communication provides e-mails, threads, attachments, questions, answer drafts, and project links. The Knowledge Engine can assemble this into conversation and project context.

### Project

Project is the primary business context. The Knowledge Engine turns project relationships into memory, timeline, evidence, and searchable context.

### Documents

Documents are root business files. The Knowledge Engine uses document metadata, versions, workflow state, extracted values, and linked communication origins as evidence.

### Workflow

Workflow provides process history through workflow instances and workflow events. The Knowledge Engine uses these events to explain what happened and what state a business object reached.

### Audit

AuditEvent records compliance and traceability information. The Knowledge Engine may include audit events in timelines and snapshots, but AuditEvent remains distinct from DomainEvent and WorkflowEvent.

### Accounting

Accounting objects will later provide invoices, invoice lines, VAT treatment, payments, bank transactions, payment matches, Merit sync outcomes, and EMTA export context.

### Policy

Policy decides what is allowed. The Knowledge Engine provides evidence and context that policy decisions may use.

### Cognitive Layer

The Cognitive Layer provides OCR, extraction, validation, confidence scoring, prompting, and reasoning capabilities. The Knowledge Engine controls the memory and context that these capabilities receive.

## 12. MVP Path

Recommended implementation sequence:

1. `KNOW-001 ProjectKnowledgeBuilder`
2. `KNOW-002 Evidence DTO`
3. `KNOW-003 ProjectTimelineBuilder`
4. `KNOW-004 KnowledgeSnapshot`
5. `KNOW-005 AIContextProvider`
6. `KNOW-006 ProjectSearchService`

The first implementation should stay DTO-based and read-only where possible. It should prove that existing communication, project, document, workflow, and audit objects can be assembled into useful context before adding new persistence structures.

## 13. Non-goals

Do not implement yet:

- vector database
- embeddings
- LLM calls
- automatic decision-making
- hidden AI reasoning without evidence

The Knowledge Engine should start as explicit, inspectable, deterministic context assembly.

## 14. Engineering Rules

- Builders read; services decide.
- Knowledge DTOs should be immutable where practical.
- Evidence must be explainable.
- AI context must be reproducible.
- Human-confirmed facts are more trusted than AI guesses.
- Builders must not mutate source objects.
- AI must receive context through controlled providers, not ad hoc database access.
- Snapshots should preserve the context used for high-risk recommendations or externally visible outputs.
- Knowledge should support audit, learning, and human review rather than bypass them.
