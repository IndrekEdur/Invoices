# Project Communication Intelligence Architecture

This document defines the architecture for linking synchronized e-mails to Projects, extracting questions, tasks, commitments, decisions and risks, reviewing AI suggestions, assigning responsibility, and preparing human-approved reminders.

This is a documentation-only architecture document. It extends the current e-mail storage, synchronization, inbox, review, project knowledge and audit layers. It does not replace them.

## Existing System Audit

Before writing this architecture, the current repository and Git history were reviewed for the communication and e-mail stack. The audit covered `EMAIL_STORAGE_ARCHITECTURE.md`, `COMMUNICATION_ARCHITECTURE.md`, `EMAIL_PROCESSING_EPIC.md`, `PROJECT_ARCHITECTURE.md`, `KNOWLEDGE_ARCHITECTURE.md`, `PLATFORM_ARCHITECTURE.md`, `UI_ARCHITECTURE.md`, `SETTINGS_ARCHITECTURE.md`, `ENGINEERING_GUIDE.md`, `DECISIONS.md`, `ROADMAP.md`, `README.md`, and recent e-mail, storage, settings, inbox, project knowledge and synchronization commits.

The implementation review covered `apps.communications` models, services, connectors, DTOs, migrations, admin registration, the manual sync command, workspace inbox and reviews services, settings e-mail account UI, `ProjectKnowledgeBuilder`, and existing e-mail-to-project review actions.

### Existing Communications Inventory

| Component | Current purpose and source of truth | Lifecycle | Decision | Boundary and known gaps |
| --- | --- | --- | --- | --- |
| `EmailAccount` | Organization-scoped provider configuration for IMAP, Microsoft 365, PST import, Gmail and other providers. | Created and edited through Settings UI; used by connectors and sync. | Retain and extend. | Provider secrets still use a placeholder; outgoing-account authorization is future work. |
| `EmailMailboxState` | Persistent mailbox cursor state for incremental IMAP sync, UIDVALIDITY, processed UID, status and safe errors. | Created per account/mailbox; updated by `EmailMailboxStateService`. | Retain unchanged for sync; extend only for additional provider cursors. | This is sync state, not intelligence run state. |
| `IMAPEmailConnector` | Provider-specific IMAP connection, mailbox snapshot, UID search, fetch, parsing and mapping to `RawEmailMessage`. | Connect, list/select mailbox, fetch raw messages, disconnect. | Retain and extend. | Attachment manifests are not fetched yet; no AI or business logic belongs here. |
| `RawEmailMessage` | Provider-neutral DTO used between connectors and import service. | Built by connector, consumed by import service. | Retain. | Should grow carefully for attachment manifests and normalized body metadata. |
| `EmailSyncService` | Provider orchestration for sync, import and optional processing hook. | Starts sync, fetches messages, imports messages, optionally runs processing, audits start/completion. | Retain. | AI processing must not be embedded in sync transactions; current optional processing is lightweight rules only. |
| `EmailImportService` | Owns persistence of `EmailThread` and `EmailMessage`. | `update_or_create` by `account + external_message_id`; refreshes thread counts. | Retain. | Imported messages are not immutable after import because re-import can update fields. Future evidence must tolerate revised sync data. |
| `EmailThread` | E-mail-specific thread record with account, external thread id, normalized subject, message count and last message time. | Created/updated during import when raw thread id exists. | Retain. | It is first-class but e-mail-specific; a broader `ProjectConversation` remains optional future design. |
| `EmailMessage` | Local synchronized message record with provider ids, body, participants, direction, thread and metadata. | Created or updated by import; read by inbox, project knowledge and review flows. | Retain. | Body text is searchable but not normalized into span-safe text; sender/recipients are raw strings/JSON, not normalized contacts. |
| `EmailAttachment` | Communication-origin attachment occurrence linked to `EmailMessage` and optionally to `Document`. | Created separately; can be converted to Document. | Retain and extend. | IMAP fetch currently ignores attachments; no attachment manifest/provider locator yet. |
| `EmailAttachmentDocumentService` | Converts an `EmailAttachment` into a `Document` through `DocumentStorageService`. | Transactional conversion, audit event, link back to attachment. | Retain. | Do not duplicate attachment binary storage or create documents for all attachments automatically. |
| `EmailProjectLink` | Current direct message-to-project relation with suggestion/review status, confidence, evidence and confirmation fields. | Created by suggestion service; confirmed/rejected/corrected by service and UI. | Retain as the first implementation of communication project links. | It is many-to-many at message level. It is not thread-level or cross-channel yet. |
| `EmailProjectSuggestionService` | Rules-based project suggestion using Project code/name in subject or body. | Creates or updates suggested links; skips confirmed/rejected links; audits suggestions. | Retain and extend. | It should become one deterministic stage before AI. Corrected-link overwrite behavior needs explicit protection in future work. |
| `EmailProjectLinkService` | Audited confirm, reject and correct lifecycle for project links. | Transactional service used by Inbox, detail and Reviews UI. | Retain. | Future generic services should wrap or migrate this, not bypass it. |
| `EmailQuestion` | Persisted detected question/action request tied to one e-mail. | Created by rule-based detection; reviewed later through draft/review flows. | Retain as an early communication question model. | It does not represent full Project tasks, commitments, risks or decisions. |
| `EmailQuestionDetectionService` | Rules-based detection using question marks and Estonian/English keywords. | Creates `EmailQuestion`, evidence and audit event. | Retain as deterministic skeleton. | It creates one broad question per matching message and can duplicate on repeated processing; future idempotency needed. |
| `EmailProcessingService` | Orchestrates project suggestions and question detection after import. | Transactional processing hook called manually or by sync when requested. | Retain as lightweight pipeline coordinator. | Future expensive AI stages need separate runs and queues. |
| `ConversationContextBuilder` | Read-only DTO builder for one e-mail, thread messages, project links, questions, attachments, documents and evidence. | Reads existing objects and returns `ConversationContext`. | Retain and extend. | It is the correct local context builder for future AI/reply services. |
| `EmailAnswerDraft` and service | Stores draft replies and review status before any future send. | Created, marked for review, approved or rejected through service and UI. | Retain. | No outbound delivery exists; approved drafts are not sent automatically. |
| Workspace Inbox | Server-rendered list/detail for imported e-mails, filters, search, project links, questions, attachments and draft actions. | Read-only list plus POST actions through services. | Retain. | Search is simple database filtering over subject/sender/body text. |
| Workspace Reviews | Lists pending project links and answer drafts needing review. | Uses services for actions. | Retain and extend. | Future communication-intelligence candidates should join this review surface. |
| Settings e-mail UI | Creates/edits e-mail accounts, masks secrets, tests IMAP connection and offers sync actions. | Workspace settings flow. | Retain. | No scheduling or OAuth yet. |
| `ProjectKnowledgeBuilder` | Aggregates project parties, addresses, e-mails, conversation contexts, questions, drafts, attachments, documents, workflow, audit, evidence and timeline. | Read-only DTO builder. | Retain and extend. | Future operational tasks and decisions should feed this builder. |
| `AuditEvent` | Append-only compliance and traceability log for human/system actions. | Created through `AuditService`. | Retain. | Do not treat it as DomainEvent or intelligence run storage. |

### Compatibility Findings

- E-mail-to-Project linking already exists through `EmailProjectLink`.
- The current relation is direct, message-level, many-to-many and status-bearing. It can be inferred by rules, then confirmed, rejected or corrected by humans.
- Threads exist as first-class `EmailThread` records, but they are e-mail-specific, not business-wide conversations.
- One IMAP server message maps deterministically to one local message through `account + external_message_id`; the current IMAP external id is based on mailbox and UID.
- Duplicate messages are prevented by the unique `EmailMessage(account, external_message_id)` constraint and `EmailImportService.update_or_create(...)`.
- Attachments and documents are separate identities. `EmailAttachment` preserves communication origin; `Document` is the business file identity.
- Server deletion does not currently delete local records. Architecture must preserve this: remote deletion is provider state, not automatic deletion of organization memory.
- Sync cursors already exist in `EmailMailboxState` with UIDVALIDITY and UID progress. UIDVALIDITY mismatch fails safe rather than silently resetting.
- Body text is stored and searchable in the current Inbox, but there is no normalized text/span model for robust evidence offsets.
- Sender and recipient identities are not normalized to contacts, Party, ProjectParty or users yet.
- Outgoing e-mails are partially represented through `EmailMessage.direction` and `EmailAnswerDraft`, but there is no outbound delivery service or sent-message import workflow yet.
- Communication records are not strictly immutable after import because re-import updates existing messages. Operational evidence should reference message identity and capture bounded excerpts/version metadata when needed.

## 1. Executive Summary

Project Communication Intelligence is the layer that interprets synchronized communication as project evidence. It links e-mails to Projects, detects questions and action candidates, proposes responsibilities and due dates, prepares reminder candidates, and records human feedback.

Synchronized e-mail records remain the source evidence. AI output is not operational truth. AI and rules can produce suggestions, but only reviewed or policy-approved decisions become Project tasks, questions, decisions, reminders or outbound communication.

Questions, tasks, commitments and decisions must remain separate concepts:

- a question expects an answer;
- a task requires action by a responsible person or party;
- a commitment states that someone will act;
- a decision records that a choice or approval has already happened.

Reminder generation and reminder sending are separate because generation is analysis, while sending is an external side effect. The first implementation must be human-in-the-loop. Continuous improvement uses structured feedback, versioned rules and evaluated datasets; it must not use uncontrolled online learning.

Target flow:

```text
E-mail provider / PST / IMAP
-> existing local e-mail storage
-> normalized message/thread representation
-> evidence extraction
-> Project-link suggestions
-> question/task/commitment/decision candidates
-> human review
-> approved Project Tasks / Questions / Decisions
-> responsibility and due dates
-> reminder candidates
-> human approval, editing or snoozing
-> later e-mail delivery
-> reply/resolution detection
-> human feedback
-> improved organization-specific intelligence
```

## 2. Architecture Position And Boundaries

The communication-intelligence layer sits above storage and sync, beside knowledge, and below human review/workflow.

1. Provider/sync layer imports evidence through connectors and `EmailSyncService`.
2. Normalized communication storage persists `EmailMessage`, `EmailThread`, `EmailAttachment` and mailbox state.
3. Thread/conversation context selects relevant messages without changing provider records.
4. Project-linking intelligence creates or updates suggestions.
5. Candidate extraction proposes questions, tasks, commitments, decisions, risks and deadlines.
6. Human review validates, edits, rejects or merges suggestions.
7. Operational Project records represent approved business state.
8. Reminder candidate generation proposes follow-ups from approved tasks/questions.
9. Human-approved delivery sends only after explicit authorization.
10. Reply/resolution detection evaluates later messages against open work.
11. Feedback and evaluation improve rules and prompts without unsafe autonomous learning.

Sync imports evidence. Intelligence interprets evidence. Review validates suggestions. Workflow and Project records represent approved business state. Sending is a later controlled side effect. No AI processing should run inside IMAP synchronization transactions.

## 3. Existing Storage Compatibility

The architecture reuses `EmailAccount`, `EmailMailboxState`, `EmailMessage`, `EmailThread`, `EmailAttachment`, `DocumentStorageService`, `EmailAttachmentDocumentService`, `EmailImportService`, incremental UID sync, current deduplication keys and current project-link relations.

Compatibility rules:

- Do not create a second e-mail message table.
- Do not create a second attachment storage model.
- Do not copy full message bodies into every candidate, task or reminder.
- Evidence records reference existing messages and bounded excerpts.
- Attachments remain in existing storage and become Documents only through the existing document boundary.
- Provider deletion must not silently delete local intelligence, Project links, tasks or history.
- Intelligence reprocessing must not require reimporting messages.
- Existing explicit Project links always outrank new suggestions.
- Sync cursor and UIDVALIDITY logic remain intact.

## 4. Message Vs Thread Vs Conversation

`EmailMessage` is the imported message evidence. In future documentation it can be described as immutable evidence, but the current implementation updates existing messages on re-import, so any evidence snapshot that needs exact text must store bounded excerpt and extraction metadata.

`EmailThread` is the existing first-class provider or reconstructed e-mail thread. It uses provider thread ids, `References`, `In-Reply-To` or normalized subject fallback from connector/import behavior.

`ProjectConversation` is an optional future business-level conversation. It may include several e-mail threads, meetings, calls, chat messages and AI conversations. It should not be added until cross-thread or cross-channel behavior requires it.

Thread reconstruction must consider:

- `Message-ID`;
- `In-Reply-To`;
- `References`;
- provider thread identifiers;
- normalized subject fallback;
- participants;
- reconstruction confidence;
- cross-project thread risk.

A whole thread must not automatically become linked to a Project merely because one message contains a weak Project signal.

## 5. Project-Linking Architecture

The first implementation should extend `EmailProjectLink`, not create a duplicate generic link table. If later channels need a generic concept, `CommunicationProjectLink` can be introduced with a compatibility migration from `EmailProjectLink`.

Future concept fields for a generic link:

- organization;
- message and/or thread;
- project;
- status;
- source;
- confidence;
- evidence;
- is_primary;
- confirmed_by and confirmed_at;
- rejected_at;
- model/rule version;
- metadata.

Statuses should include `suggested`, `confirmed`, `rejected` and `superseded` or reuse the current `corrected` behavior during migration.

Sources should include exact project code, existing thread link, explicit user link, known participant, attachment filename, document link, subject keyword, semantic model and imported legacy link.

Confidence hierarchy:

- exact Project code in normalized subject/body: high;
- previously confirmed same thread with no conflicting evidence: high but reviewable;
- explicitly linked attachment/document: high;
- known Project participant only: medium or weak;
- semantic similarity only: suggestion requiring review.

One message may link to multiple Projects where genuinely necessary. One primary Project can be introduced later, but no weak rule should force a primary link without review.

## 6. Deterministic Rules Before AI

The rule pipeline runs before semantic AI:

- exact Project code;
- recognized Project aliases;
- existing confirmed message/thread link;
- reply to a confirmed Project message;
- attachment/document already linked to Project;
- explicitly mapped mailbox/folder where applicable;
- known recipient/sender combined with other evidence.

Rules must be versioned, explainable, organization-scoped, testable and non-destructive. AI must not replace strong deterministic evidence. Deterministic outputs can still require review when risk or ambiguity is high.

## 7. Communication Intelligence Candidate Types

Canonical candidate types:

- `question`: someone expects an answer;
- `task_request`: someone is asked to perform an action;
- `commitment`: someone states that they will perform an action;
- `decision`: a choice or approval has been made;
- `risk`: potential future problem;
- `blocker`: current obstacle preventing progress;
- `deadline`: date/time constraint attached to another candidate;
- `information_only`: no follow-up action;
- `resolution_evidence`: a later message may answer or complete an existing item.

One text span may produce several related candidates, but duplicate operational tasks must be prevented.

## 8. Evidence Model

Future `CommunicationEvidence` should reference existing source records rather than copy them.

Conceptual references:

- `EmailMessage`;
- optional `EmailAttachment` or `Document`;
- text span start/end where practical;
- bounded quoted excerpt;
- detected language;
- evidence type;
- extractor version;
- metadata.

Operational records reference evidence. Full e-mail bodies are not duplicated. HTML and plain-text offsets require a normalized-text policy before offsets are trusted. Sensitive content remains organization-scoped.

## 9. Candidate Model

Future `CommunicationIntelligenceCandidate` represents a suggestion, not an operational task or decision.

Conceptual fields:

- organization;
- candidate_type;
- status;
- project suggestion;
- message and/or thread;
- title suggestion;
- description suggestion;
- responsible-party suggestion;
- due-date suggestion;
- priority suggestion;
- confidence;
- evidence summary;
- extraction method;
- model version;
- rule version;
- review timestamps/users;
- rejection reason;
- merged_into candidate/task;
- metadata;
- created_at and updated_at.

Statuses: `pending_review`, `approved`, `edited_and_approved`, `rejected`, `duplicate`, `merged`, `expired`.

## 10. Human Review Queue

The existing `/workspace/reviews/` surface should be extended before introducing a separate route. A future `/workspace/reviews/communications/` route is more precise than `/workspace/ai-review/` because reviews are business decisions, not only AI review.

Review cards should show:

- source e-mail;
- sender;
- received date;
- Project suggestion and confidence;
- candidate type;
- extracted question/action;
- proposed responsible person;
- proposed due date;
- evidence;
- similar existing open tasks/questions;
- reason for suggestion;
- model/rule version.

Actions:

- approve;
- edit and approve;
- reject;
- not actionable;
- wrong Project;
- merge with existing;
- defer/snooze review.

No outbound communication is sent from candidate approval.

## 11. Operational Project Records

The current workflow models define process structure and execution history. `ProjectKnowledgeBuilder` aggregates existing communication, document, workflow and audit context. Neither currently replaces explicit operational Project questions, tasks, decisions or risks.

Preferred distinction:

- `ProjectQuestion`: expects an answer and may later generate a task.
- `ProjectTask`: actionable responsibility with assignee, due date and status.
- `ProjectDecision`: finalized choice, approval or business history.
- `ProjectRisk` or `ProjectBlocker`: issue requiring tracking or mitigation.

If one generalized work-item model is later preferred, it must enforce typed subcategories and invariants so a decision cannot behave like an unfinished task.

## 12. Task And Responsibility Model

Future task concepts:

- organization;
- project;
- title;
- description;
- task type;
- status;
- priority;
- responsible person/contact/ProjectParty;
- accountable person;
- requested by;
- due date;
- reminder policy;
- source confidence;
- human reviewed;
- created from candidate;
- completed at;
- resolution reason;
- metadata.

Statuses may include `open`, `in_progress`, `waiting_external`, `waiting_internal`, `completed`, `cancelled` and `dismissed`.

Responsibility must support authenticated internal users, ProjectParty/person/contact, external e-mail recipient and unassigned state. Do not assume every external e-mail address is a system user.

## 13. Candidate-To-Task Deduplication

Duplicate detection should use:

- same message/evidence;
- same thread;
- same Project;
- semantic similarity;
- same requested deliverable;
- same responsible person;
- overlapping due date;
- prior approved candidate.

The system should suggest create new, link as new evidence to existing task, merge, or ignore as duplicate. Low-confidence candidates must not be merged automatically. One task may have evidence from multiple messages.

## 14. Reply And Resolution Detection

Later messages can be evaluated against open questions and tasks.

Potential outcomes:

- fully answered or completed;
- partially answered;
- acknowledgement only;
- new question;
- requested attachment missing;
- deadline changed;
- responsibility changed;
- no resolution.

AI or rules suggest a transition. A human validates initially. A new reply must never automatically close a task merely because it exists in the same thread.

## 15. Reminder Candidate Architecture

Reminder flow:

```text
Task state
-> reminder eligibility
-> reminder candidate
-> human decision
-> delivery
```

Future `ReminderCandidate` fields:

- organization;
- task;
- recipient;
- reason;
- suggested subject/body;
- status;
- generated_at;
- due/overdue context;
- last reminder history;
- source task snapshot;
- model/template version;
- approved/edited/snoozed/dismissed by/at;
- snooze_until;
- metadata.

Statuses: `pending_review`, `approved`, `edited_and_approved`, `snoozed`, `dismissed`, `sent`, `failed`, `cancelled`.

Reminder candidate generation must not send e-mail.

## 16. Reminder Policy

Future policies:

- due soon;
- overdue;
- no response for N days;
- commitment date passed;
- waiting_external too long;
- waiting_internal too long.

Policy may be organization-, Project- or task-specific. Initial mode is human-controlled with no fully automatic sending.

Reminder idempotency fingerprint:

- task;
- recipient;
- policy;
- reminder cycle/window;
- task version/state.

The same unresolved task must not generate duplicate reminder candidates every day.

## 17. Human Approval And Snooze

Review actions:

- send now;
- edit and send;
- approve for later sending;
- snooze one day;
- snooze until date;
- do not remind again;
- mark waiting;
- mark completed;
- change responsible person.

Snooze affects the reminder candidate or reminder policy, not the underlying evidence. Every outbound action remains reviewable and audited in the initial phase.

## 18. Outbound E-Mail Boundary

Delivery is a later implementation. Future `CommunicationDeliveryService` must:

- use an approved `ReminderCandidate` or explicit user action;
- resolve authorized sender account;
- preserve thread/reply headers where appropriate;
- store delivery attempt/history;
- store safe provider result;
- avoid duplicate sends;
- never expose account secrets;
- prevent AI from directly calling SMTP/provider clients.

Approved drafts and reminders are still not sent until the delivery service exists.

## 19. AI Processing Pipeline

AI-capable processing stages:

- message eligibility;
- normalization;
- deterministic Project rules;
- thread context selection;
- candidate extraction;
- Project ranking;
- responsibility ranking;
- due-date parsing;
- duplicate search;
- candidate persistence;
- human review.

Expensive AI processing must not run synchronously inside IMAP import. Initial implementation may use commands or manual processing, but the architecture should support queued jobs later.

## 20. AI Provider Boundary

Future provider-independent interface: `CommunicationIntelligenceProvider`.

Methods:

- `suggest_project_links(...)`;
- `extract_candidates(...)`;
- `assess_resolution(...)`;
- `draft_reminder(...)`.

Inputs are bounded structured context, not unrestricted database access. Outputs are validated against schemas/DTOs. Provider output never directly mutates operational records.

Provider boundary requirements:

- timeouts;
- retries;
- safe errors;
- token/cost tracking;
- redaction policy;
- prompt/model versions;
- provider substitution;
- deterministic test doubles.

No specific AI provider is a hard dependency of this architecture.

## 21. Confidence Model

Confidence is contextual, not an objective probability unless calibrated.

Store separately:

- Project-link confidence;
- candidate-type confidence;
- responsibility confidence;
- due-date confidence;
- resolution confidence.

Automation thresholds must be configurable. Initial rule: all AI-generated candidates require review. Future high-confidence deterministic Project links may be auto-confirmed only under explicit organization policy.

## 22. Continuous Improvement And Feedback

Future `CommunicationHumanFeedback` should capture:

- reviewed candidate;
- original suggestion;
- final human decision;
- edited title/description/project/responsible/due date;
- rejection reason;
- duplicate/merge target;
- reviewer;
- rule/model version;
- metadata.

Feedback can improve:

- rule tuning;
- prompt/example tuning;
- organization-specific retrieval examples;
- confidence calibration;
- evaluated classifier/fine-tuning only after sufficient clean labels.

Do not learn from unverified AI guesses. Do not apply uncontrolled online learning to production behavior.

## 23. Evaluation And Quality Metrics

Measure future quality through:

- Project-link precision and correction rate;
- candidate approval rate;
- rejection reasons;
- duplicate rate;
- missed-question reports;
- false closure reports;
- reminder approval/snooze/dismissal rate;
- time to resolution;
- per-model/rule version comparisons.

Evaluation datasets should use reviewed, versioned examples. Automated tests use mocked providers only.

## 24. Automation Levels

Automation levels:

- level 0: no suggestion;
- level 1: suggestion only;
- level 2: suggested action requiring human approval;
- level 3: policy-approved internal update;
- level 4: policy-approved external side effect;
- level 5: autonomous end-to-end process.

The initial Project Communication Intelligence implementation is level 1 or level 2. External e-mail sending remains below level 3 until policy, permissions, review history and audit controls exist.

## 25. Project UI Integration

Project Workspace should show communication intelligence in context:

- confirmed and suggested e-mails;
- open questions;
- approved tasks;
- decisions;
- risks/blockers;
- reminder candidates;
- evidence and source excerpts;
- resolution state;
- review history.

The existing Project Workspace already uses `ProjectKnowledgeBuilder`; future task/question/decision records should be added to that builder rather than queried ad hoc in templates.

## 26. Central Workspace Integration

The Dashboard and Reviews workspace should surface:

- pending Project-link suggestions;
- candidate reviews;
- overdue or due-soon tasks;
- draft replies;
- reminder candidates;
- failed processing runs;
- feedback/quality exceptions.

The Inbox remains the source interaction for individual e-mails. Reviews is the operational queue. Projects is the context workspace.

## 27. Identity And Participant Resolution

Current e-mail participants are raw sender/recipient values. Future identity resolution should map:

```text
raw e-mail address
-> normalized contact/person
-> ProjectParty
-> internal User, organization employee or external party
```

Do not identify a responsible person solely from display-name text when multiple contacts match. Maintain aliases and history. External contacts may receive reminders only after explicit authorization.

## 28. Security, Privacy And GDPR

Requirements:

- organization isolation;
- least-privilege access;
- sensitive message content protection;
- AI provider data transfer controls;
- configurable redaction;
- retention policy;
- deletion/legal hold interactions;
- user audit;
- outbound authorization;
- prompt-injection defense for e-mails and attachments;
- attachment malware/content-safety boundary;
- no secrets in prompts/logs;
- no cross-organization examples.

E-mail content is untrusted input. Instructions inside an e-mail must never override system, developer, organization, policy or user authorization rules.

## 29. Attachment And Document Intelligence

Reuse existing attachment/document storage. Future extraction may inspect:

- filename;
- MIME type;
- safe extracted text;
- document classification;
- Project code;
- requested deliverable presence.

Do not duplicate attachment binaries. Unsupported, encrypted or oversized files should produce safe evidence gaps, not failed mailbox sync. OCR is a separate expensive pipeline. Document and attachment evidence must remain traceable.

## 30. Idempotency And Reprocessing

Processing fingerprints should include:

- message;
- task type;
- extractor/rule/model version;
- normalized content version.

Reprocessing after a model upgrade may create a new candidate version but must not duplicate approved operational tasks. Support reprocess one message, one thread, a date range, dry run, compare old/new extraction, and retain prior decisions. Manual corrections must not be overwritten by reprocessing.

## 31. Run Tracking

Future `CommunicationIntelligenceRun` should track:

- organization;
- account/mailbox;
- period/message scope;
- status;
- model/rule version;
- processed count;
- suggested count;
- skipped count;
- failed count;
- safe error;
- token/cost metrics;
- timestamps;
- metadata.

`EmailMailboxState` should not be reused for this. It is sync cursor state, not intelligence run state. No raw message contents belong in run metadata.

## 32. Failure Handling

One failed message must not fail the entire mailbox intelligence run.

Failure categories:

- normalization error;
- unsupported encoding;
- missing body;
- provider timeout;
- schema validation failure;
- invalid Project suggestion;
- duplicate candidate conflict;
- stale source message.

Never lose imported e-mail because intelligence failed. Intelligence failures should be retryable and visible in review/settings surfaces where useful.

## 33. Audit Model

Reuse `AuditEvent` for material human or operational transitions:

- Project link confirmed/rejected/corrected;
- candidate approved/rejected/merged;
- task created/edited/reassigned/completed;
- reminder approved/snoozed/dismissed/sent;
- automated policy enabled/disabled.

Do not create audit events for every read or unchanged reprocessing attempt. Processing run metadata provides automatic traceability; audit records business-significant decisions.

## 34. Notification And Scheduling Boundary

Separate future components:

- task evaluation;
- reminder candidate generation;
- human review;
- delivery scheduling;
- e-mail sending;
- reply detection.

Do not combine all of these into one reminder service. Initial cadence can be daily candidate generation and human review. Automatic weekly summaries/reminders are later.

## 35. Feature Usage/Product Analytics Compatibility

Future measurement may include:

- candidates reviewed;
- approval/correction rates;
- wizard abandonment;
- reminder approval/snooze rates;
- time to resolve;
- feature usage.

Do not implement product analytics now. Avoid storing every UI click in domain tables.

## 36. Service Boundaries

| Service | Inputs | Outputs/writes | Forbidden responsibilities |
| --- | --- | --- | --- |
| `CommunicationProjectLinkService` | Existing messages, Projects, evidence, actor | Suggested/confirmed/rejected links | Importing messages, sending e-mails, creating tasks directly |
| `CommunicationThreadService` | Messages and headers | Thread summaries or optional conversation records | Provider fetch, Project auto-linking from weak evidence |
| `CommunicationIntelligenceService` | Bounded context DTOs | Candidates and evidence references | Direct operational mutation, outbound delivery |
| `CommunicationCandidateReviewService` | Candidate, reviewer decision | Approved/rejected/merged candidate state and operational record request | AI calls, provider sync |
| `ProjectTaskService` | Approved candidate or user command | Project task/question/decision records | Reading mailbox providers, generating reminders |
| `TaskResponsibilityService` | Project parties, contacts, users, evidence | Responsibility suggestions or assignments | Trusting display names alone |
| `ReminderCandidateService` | Approved tasks/questions and policy | Reminder candidates | Sending e-mail |
| `ReminderReviewService` | Candidate and reviewer action | Approved/snoozed/dismissed reminder state | SMTP/provider calls |
| `CommunicationDeliveryService` | Approved delivery command | Delivery attempt/result records | Creating unapproved reminders, reading secrets outside connector boundary |
| `ReplyResolutionAssessmentService` | Open task/question plus later messages | Resolution candidates | Auto-closing high-risk tasks |
| `CommunicationFeedbackService` | Review corrections | Structured feedback | Uncontrolled online learning |

## 37. Suggested Domain Model

Existing reused models:

- `EmailAccount`
- `EmailMailboxState`
- `EmailThread`
- `EmailMessage`
- `EmailAttachment`
- `EmailProjectLink`
- `EmailQuestion`
- `EmailAnswerDraft`
- `Document`
- `Project`
- `ProjectParty`
- `ProjectKnowledge` DTO
- `AuditEvent`

Proposed new models when implementation starts:

- `CommunicationEvidence`: bounded source references for candidates and operational records.
- `CommunicationIntelligenceCandidate`: pending suggestions for questions, tasks, commitments, decisions, risks and deadlines.
- `ProjectTask` or typed `ProjectWorkItem`: approved actionable work.
- `ProjectDecision`: durable approved decision history if not covered by future work-item typing.
- `ReminderCandidate`: proposed reminder, never delivery by itself.
- `CommunicationHumanFeedback`: structured review feedback.
- `CommunicationIntelligenceRun`: processing run state separate from mailbox sync.

Optional future models:

- `ProjectConversation`: only if business conversations need to span multiple e-mail threads or channels.
- `CommunicationDelivery`: when outbound sending is implemented.
- normalized contact/person/party aliases for sender and recipient resolution.

Rejected duplicates:

- second `EmailMessage` model;
- second attachment storage model;
- AI-only task table that bypasses Project services;
- reminder model that sends e-mail as a side effect of generation;
- provider-specific business intelligence tables.

## 38. Implementation Sequence

Adjusted roadmap based on the audit:

- `EMAIL-PROJ-001`: Extend deterministic e-mail-to-Project linking using existing `EmailProjectLink`; add idempotency and protect corrected links.
- `EMAIL-THREAD-001`: Improve thread normalization and thread-derived evidence only if current `EmailThread` proves insufficient.
- `EMAIL-INTEL-001`: Add read-only candidate extraction for question/task/commitment/decision/risk types; no AI provider call at first unless mocked.
- `MVP-COMM-REVIEW-001`: Extend existing Reviews workspace with communication-intelligence candidate cards.
- `TASK-001`: Add operational Project Task/Question/Decision or typed work-item model after reviewing workflow reuse.
- `TASK-002`: Add Project and central Task UI.
- `REMINDER-001`: Add reminder candidate engine; no delivery.
- `MVP-REMINDER-001`: Add human approval/edit/snooze UI.
- `REMINDER-002`: Add approved outbound e-mail delivery through a dedicated service.
- `EMAIL-REPLY-001`: Add reply and resolution assessment.
- `AI-FEEDBACK-001`: Add structured feedback and quality dashboard.

Implementation note for `EMAIL-PROJ-001`:

- The first deterministic implementation reuses `EmailProjectLink` as the current authoritative relation instead of adding a duplicate `CommunicationProjectLink` table.
- `EmailProjectLink` carries source, confidence band, primary flag, evidence summary, rule version, fingerprint and last evaluation metadata for deterministic suggestions.
- Exact Project code evidence, confirmed thread evidence, attachment/document evidence and participant support are evaluated by a service layer outside mailbox sync transactions.
- Suggested links remain reviewable; confirmed links feed Project Communications. Suggested or rejected links are not treated as operational Project communication.
- AI, semantic similarity, task extraction, reminders, outbound delivery and automatic high-confidence confirmation remain future phases.

## 39. Migration And Backwards Compatibility

Preserve:

- imported messages;
- attachments;
- sync cursors;
- current Project links;
- current Inbox state;
- current Knowledge DTO behavior;
- existing audit history;
- existing tests;
- provider identifiers.

No destructive migration. Existing confirmed Project links outrank new suggestions. Existing operational records must not be recreated from old messages without a controlled backfill. If `CommunicationProjectLink` is ever introduced, migrate or wrap `EmailProjectLink` rather than running two independent link systems.

## 40. Testing Strategy

Future tests should cover:

- storage boundary: intelligence failure does not affect sync/import; no message/attachment mutation;
- Project linking: exact code, thread inheritance, ambiguous participants, multiple Projects, rejection, manual correction, organization isolation, idempotency;
- extraction: question/task/commitment/decision distinctions, multiple candidates, no-action message, quoted history exclusion, signatures, multilingual content, prompt injection and schema validation;
- review: approve, edit, reject, merge, no direct AI mutation, feedback captured;
- tasks: responsibility, due date, evidence, duplicate prevention, lifecycle;
- reminders: candidate generation, no duplicate reminders, snooze, human approval, no unauthorized send;
- resolution: full vs partial answer, attachment missing, false closure protection;
- AI provider: mocked only in automated tests, no real provider calls, timeouts, safe errors and version metadata.

## 41. Non-Goals

This task does not implement:

- new models;
- migrations;
- AI provider calls;
- message processing;
- Project linking changes;
- task creation;
- UI;
- reminder generation;
- e-mail sending;
- scheduling;
- online model training;
- vector database;
- OCR pipeline;
- Slack/SMS;
- autonomous task completion;
- automatic reply sending.

## 42. Documentation Updates

This document should be linked from `README.md`. `ROADMAP.md` should state the current architecture phase as Project Communication Intelligence Architecture. `DECISIONS.md` should record that existing e-mail storage remains authoritative, intelligence is a separate layer, AI outputs are suggestions, operational records require human approval initially, reminder generation and sending are separate, continuous improvement uses versioned feedback, and AI logic does not belong inside mailbox sync transactions.

The feature index file does not currently exist and should not be created for this task.

## Architecture Review Checklist

- Existing communications code was inspected, not assumed.
- EMAIL-STORAGE-002 actual state was verified through code and history.
- No second `EmailMessage` or attachment storage is proposed.
- Existing sync cursor and UIDVALIDITY logic remains intact.
- Existing explicit Project links are preserved.
- Thread/message/conversation boundaries are clear.
- Questions, tasks, commitments and decisions are distinct.
- Candidates are separate from operational records.
- AI never mutates operational state directly.
- Reminder generation and sending are separate.
- Source evidence is traceable.
- Duplicate tasks/reminders are prevented by fingerprints and review.
- Human feedback is structured and versioned.
- Reprocessing cannot overwrite manual decisions.
- Organization isolation, GDPR and prompt-injection risks are covered.
- Implementation roadmap reflects what already exists.
