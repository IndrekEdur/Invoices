# Architecture Consistency Review

Date: 2026-07-14

This review checks the platform architecture documents as one system. It is documentation-only and does not introduce code, models, migrations, services, UI or tests.

## Executive Summary

The architecture is broadly coherent. The strongest shared platform ideas are consistent across the documents:

- `Organization` is the platform tenant root.
- `Project` is the primary business context.
- Merit remains the accounting source of truth.
- Workspace owns operational context, review, evidence, knowledge, dashboards and controlled user actions.
- Synchronized data is read-model or cache data unless explicitly described otherwise.
- Services own business actions; templates and models should stay thin.
- AI/cognitive capabilities suggest, explain and draft, but do not own business truth.
- Human approval, audit, organization isolation and explainability are repeated consistently.

Consistency score: 8.1 / 10.

The score is strong because the newest architecture documents align around service boundaries, evidence, human review and source-of-truth rules. The main deductions are for naming drift and repeated future concepts that are described in several places without one canonical lifecycle document yet. The biggest risks are not contradictions in principles; they are future implementation ambiguity around tasks/questions/decisions, reminders/notifications, review queues, run tracking and evidence.

## Architecture Inventory

Reviewed core documents:

- `README.md`
- `ROADMAP.md`
- `DECISIONS.md`
- `ENGINEERING_GUIDE.md`
- `ARCHITECTURE.md`
- `ARCHITECTURE_REVIEW.md`
- `SPECIFICATION.md`
- `MASTER_ARCHITECTURE.md`
- `ENTERPRISE_DOMAIN_MAP.md`
- `PLATFORM_ARCHITECTURE.md`
- `MVP_ROADMAP.md`
- `UI_ARCHITECTURE.md`
- `SETTINGS_ARCHITECTURE.md`
- `PROJECT_ARCHITECTURE.md`
- `COMMUNICATION_ARCHITECTURE.md`
- `EMAIL_PROCESSING_EPIC.md`
- `EMAIL_STORAGE_ARCHITECTURE.md`
- `PROJECT_COMMUNICATION_INTELLIGENCE_ARCHITECTURE.md`
- `KNOWLEDGE_ARCHITECTURE.md`
- `MERIT_INTEGRATION_ARCHITECTURE.md`
- `MERIT_VERIFICATION_GUIDE.md`
- `FINANCIAL_REPORTING_ARCHITECTURE.md`
- `FINANCIAL_GL_VERIFICATION_GUIDE.md`
- `MANAGEMENT_COST_ALLOCATION_ARCHITECTURE.md`
- `FINANCIAL_ALERT_ARCHITECTURE.md`

The feature index document is not present and was not created.

## Strengths

The platform now has a clear center of gravity: Operations Workspace Platform, organized around Organization, Project, Communication, Documents, Workflow, Knowledge, Accounting, Settings, Review and AI assistance.

Source-of-truth boundaries are mostly consistent:

- Merit is the accounting authority.
- Workspace GL records are synchronized read models.
- Management allocations are internal management reporting records.
- Financial alerts are persisted lifecycle records based on existing financial services.
- E-mail storage is the authoritative communication evidence layer.
- Document is the business file identity, while EmailAttachment is communication origin.
- AuditEvent is compliance and traceability, not DomainEvent or WorkflowEvent.

The service-layer rule is repeated and applied well. Documents consistently say that views, templates, models and connectors should not own business decisions.

The AI posture is consistent. AI provides suggestions, drafts, explanations and confidence. Human approval, policy and workflow remain authoritative.

The financial architecture is particularly well-aligned after recent work: Project financial aggregation, management allocation, alert evaluation and reporting are separated without modifying synchronized Merit data.

## Weaknesses

Several future concepts are repeated across documents without a single canonical lifecycle:

- Task
- Question
- Decision
- Risk
- Reminder
- Notification
- Review
- Evidence
- Candidate
- Run
- Conversation

The older legacy documents still describe invoice-automation-specific target app boundaries that no longer match the Operations Workspace Platform. They are useful historical context, but they should be clearly marked as legacy reference documents.

`ROADMAP.md` carries several "current" labels at once. Some are accurate by category, but the page reads as if the current implementation is still Platform Core while README shows advanced financial and workspace features already implemented.

Some architecture documents include stale task names in "MVP Path" sections. For example, communication and email storage MVP paths list earlier COMM or EMAIL-STORAGE tasks that are now partially or fully implemented.

## Detected Inconsistencies

| Area | Issue | Severity | Recommendation |
| --- | --- | --- | --- |
| Communication project links | `ProjectCommunicationLink`, `CommunicationProjectLink` and `EmailProjectLink` describe overlapping concepts. | Medium | Canonical current implementation: `EmailProjectLink`. Canonical future cross-channel concept: `CommunicationProjectLink`, migrated from or wrapping `EmailProjectLink`. |
| Conversation terminology | `Conversation`, `EmailThread`, `ProjectConversation` and thread context are used at different abstraction levels. | Medium | Keep `EmailThread` for e-mail-specific grouping. Use `Conversation` only for cross-channel business context. Introduce `ProjectConversation` only when cross-thread or cross-channel behavior exists. |
| Review terminology | `ReviewTask`, Reviews workspace, alert acknowledgement, draft approval and candidate review overlap. | Medium | Add a future Review Architecture defining Review as a workspace queue/pattern, not one generic model by default. |
| Reminder vs notification | Communication reminders, financial alert digest, report delivery and platform notifications all mention future sending. | High | Add Notification and Delivery Architecture before implementing any outbound digest/reminder/report delivery. |
| Evidence | Evidence appears in matching, knowledge, project links, alerts, financial reporting and communication intelligence. | Medium | Define one evidence vocabulary owned by Knowledge architecture, with domain-specific evidence records or DTOs referencing source objects. |
| Candidate | Candidate means invoice candidate, match candidate, communication intelligence candidate and alert candidate depending on document. | Low | Always qualify candidate names: `InvoiceCandidate`, `PaymentMatchCandidate`, `CommunicationIntelligenceCandidate`, `ReminderCandidate`. |
| Run tracking | E-mail mailbox state, accounting sync state, GL sync runs, financial alert evaluation runs and future communication intelligence runs share a shape but not a common vocabulary. | Medium | Add a Platform Run/Job architecture or glossary. Do not force one generic table yet. |
| Status values | Similar states use different words: suggested, pending_review, needs_review, approved, confirmed, acknowledged, dismissed, resolved, corrected, superseded. | Medium | Create a lifecycle/status glossary before the next cross-domain review or notification work. |
| Legacy app architecture | `ARCHITECTURE.md`, `ARCHITECTURE_REVIEW.md` and `SPECIFICATION.md` still reflect invoice automation and target app boundaries from the migration period. | Low | Mark as legacy/prototype references and clarify that `PLATFORM_ARCHITECTURE.md` plus `MASTER_ARCHITECTURE.md` are current platform references. |
| Roadmap current labels | Roadmap has current architecture, product, engineering, implementation phase, implementation and focus, which can conflict at a glance. | Medium | Split into "Current architecture", "Current product", "Current implementation" and "Current implementation focus" with dates or maintain a short changelog. |

## Domain Consistency Review

### Projects

Consistent. Project is repeatedly described as the primary business context and organizational memory container. Project codes align with Merit dimensions. Project Workspace, financials, communication, knowledge and management allocations all use Project as a cross-domain anchor.

Open issue: Project tasks, decisions, phases and timeline are architectural concepts but not yet governed by a canonical lifecycle document.

### Accounting

Consistent. Merit is authoritative; Workspace caches and interprets data. API logic belongs in connectors. Services own sync, dimension value creation and GL synchronization. Workspace views should not call Merit directly.

Open issue: invoice, sales invoice, payment and bank reconciliation are still mostly future or legacy concepts; financial reporting architecture gives the best future map.

### Management Allocations

Consistent. Management allocations are separate from Merit GL cache and from accounting truth. Approved allocation versions are immutable and auditable. Project-source allocations use `ProjectFinancialAggregationService` and report allocated-in/out separately.

Open issue: future revision/audit enhancements should remain in the allocation service family and not leak into project financial aggregation formulas.

### Financial Reporting

Consistent. `ProjectFinancialAggregationService` owns project financial truth from synchronized GL allocation rows. Workspace charts and templates are read-side presentation only. Mixed-currency handling is consistently treated as a data-quality issue.

Open issue: frozen financial snapshots and report delivery are future concepts and should not be conflated with live dashboard aggregation.

### Financial Alerts

Consistent. Financial alerts are persisted lifecycle records. Alert policy is separate from financial fact. Alert detection consumes existing financial services and should not duplicate financial formulas. Notification is explicitly future.

Open issue: alert notification must align with the broader future Notification and Delivery architecture.

### Email Storage

Consistent. The Workspace is not a mirror of IMAP. Remote deletion must not delete Workspace memory. `EmailMessage`, `EmailThread`, `EmailAttachment`, `EmailMailboxState`, `EmailImportService` and `EmailSyncService` are the storage/sync foundation.

Open issue: architecture describes immutable normalized communication storage, while current import updates existing `EmailMessage` rows. The newest communication intelligence document correctly identifies this compatibility issue.

### Communication Intelligence

Consistent with storage and AI principles. It correctly extends existing e-mail storage and current `EmailProjectLink`, `EmailQuestion`, `EmailAnswerDraft`, Inbox and Reviews flows instead of duplicating them.

Open issue: future task/question/decision/reminder models need their own canonical implementation architecture before code.

### Workspace

Consistent. Workspace is the product surface and should call services. Dashboard, Inbox, Projects, Reviews, Financials, Alerts and Settings are read/review/action surfaces, not business logic owners.

Open issue: "Dashboard" and "Workspace" are sometimes used loosely. Dashboard should mean one Workspace area, not the whole product.

### Settings

Consistent. Settings is operational control, not Django Admin. Secrets are masked. Test connection and sync actions use connectors/services. Configuration is Organization-scoped and audited for sensitive changes.

Open issue: future user/role/permission settings need more detail before security-sensitive UI expands.

### Documents

Consistent. Document is the business file identity. EmailAttachment is source occurrence. DocumentStorageService owns file storage. Document status and Workflow state are separate.

Open issue: OCR/classification/extraction remains future and should stay under Cognitive/Capability boundaries.

### Audit

Consistent. AuditEvent is append-only compliance and traceability. It is not DomainEvent and not WorkflowEvent. Services should use AuditService.

Open issue: many future lifecycle records mention audit, but not all specify exact event names or metadata shape. That can wait until implementation tasks.

### Users And Organizations

Organization is consistent as tenant root. User/Profile concepts are present. Role/Permission is not deeply implemented yet but is consistently described as future access control.

Open issue: `Company Owner` appears as a user role label in UI/product documents; it should remain a role/persona phrase, not a platform root entity.

### Tasks, Questions, Decisions And Risks

Concepts are consistent at a high level but incomplete. Communication architecture, Project architecture, Enterprise Domain Map and communication intelligence all agree that these are distinct. No canonical lifecycle/source-of-truth architecture exists yet.

Recommendation: create a Project Work Architecture document before implementing ProjectTask/ProjectQuestion/ProjectDecision/ProjectRisk.

### Reminders And Notifications

Consistent in principle: generation/selection is separate from delivery/sending. No architecture should send automatically without approval/policy.

Open issue: reminders, alert digests, report deliveries and platform notifications need one future boundary document.

### AI

Very consistent. AI does not own truth. AI suggests, drafts, extracts, classifies or ranks. Human review, policy and workflow decide. Knowledge provides controlled context. Feedback must be structured and versioned.

Open issue: provider boundary and model/version logging are described but not centralized in one implementation-ready prompt/provider architecture.

### Review Queues

Consistent as product need, but not yet modeled consistently. Current Workspace Reviews handles project links and drafts; financial alerts have their own list; future candidates and reminders need review.

Recommendation: treat "Review" as a Workspace pattern first, not a universal `ReviewTask` model unless implementation proves the need.

### Knowledge And Timeline

Consistent. Knowledge builders read existing domain objects and return structured context. Evidence and timelines support AI and explainability. Knowledge does not mutate source objects.

Open issue: timeline event shapes differ between project knowledge, workflow, audit and financial domains. A lightweight timeline entry contract would help.

## Entity Consistency

| Entity | Canonical meaning | Consistency assessment |
| --- | --- | --- |
| Organization | Tenant/root context for all platform data. | Consistent. |
| Project | Primary business context and memory container. | Consistent. |
| ProjectParty | Project-scoped participant until global Party exists. | Consistent, with future migration path needed. |
| Party | Future/global legal or natural person concept. | Consistent, not fully implemented. |
| Contact | Not canonical yet; should be future identity/participant layer. | Needs definition. |
| EmailMessage | Local synchronized e-mail record and source evidence. | Consistent, with immutability caveat. |
| EmailThread | E-mail-specific thread grouping. | Consistent. |
| Conversation | Cross-channel business communication context. | Needs future canonical model only if needed. |
| Document | Business file identity/root aggregate. | Consistent. |
| Attachment | Source occurrence, not business document identity. | Consistent. |
| Task | Future actionable Project work item. | Needs canonical architecture. |
| Question | Expected answer; may become task. | Mostly consistent; current EmailQuestion is message-scoped. |
| Decision | Approved or finalized business choice. | Needs canonical architecture. |
| Risk | Potential or current issue needing tracking. | Needs canonical architecture. |
| Reminder | Ambiguous unless qualified. | Prefer `ReminderCandidate`, `ReminderDelivery`, `ReminderPolicy`. |
| Alert | Operational condition requiring visibility/review. | Consistent when qualified as FinancialAlert. |
| FinancialAlert | Persisted project/organization financial alert lifecycle. | Consistent. |
| ManagementAllocation | Internal management accounting layer, separate from Merit. | Consistent. |
| AllocationVersion | Immutable version within allocation lifecycle. | Consistent. |
| Evidence | Source support for suggestions/decisions. | Consistent principle, needs shared schema. |
| Candidate | Suggestion not yet operational truth. | Needs qualified names. |
| Review | Human validation workflow. | Consistent pattern, model ownership unclear. |
| Run | Sync/evaluation/processing attempt. | Needs platform vocabulary. |
| AuditEvent | Append-only compliance trace. | Consistent. |
| User | Authenticated platform actor. | Consistent but role architecture is future. |

## Service Consistency

Authoritative service ownership should remain:

| Responsibility | Authoritative service/boundary |
| --- | --- |
| Audit recording | `AuditService.record(...)` |
| Organization creation | `OrganizationService` |
| Document storage | `DocumentStorageService` |
| Document status | `DocumentStatusService` |
| Workflow execution | `WorkflowEngine` |
| E-mail provider fetch | Provider connector, such as `IMAPEmailConnector` |
| E-mail persistence | `EmailImportService` |
| E-mail sync orchestration | `EmailSyncService` |
| Mailbox cursor state | `EmailMailboxStateService` |
| E-mail-to-project review | `EmailProjectLinkService` |
| Conversation context | `ConversationContextBuilder` |
| Project knowledge | `ProjectKnowledgeBuilder` |
| Merit HTTP | `MeritAPIClient` |
| Merit auth | `MeritAuthenticationService` and `SecretProvider` |
| Dimension cache sync | `AccountingDimensionSyncService` |
| Project code allocation | `ProjectCodeAllocationService` |
| Project creation | `ProjectCreationService` |
| GL sync | `GeneralLedgerSyncService` |
| Project financial aggregation | `ProjectFinancialAggregationService` |
| Management financial aggregation | `ProjectManagementFinancialService` |
| Allocation proposal/review | Management allocation services |
| Financial alert evaluation | `FinancialAlertEvaluationService` |

Potential service risks:

- Future `CommunicationIntelligenceService` must not subsume `EmailSyncService` or `EmailImportService`.
- Future `ReminderCandidateService` must not send e-mail.
- Future delivery services must not generate business candidates.
- Future review services must not duplicate domain-specific lifecycle services.
- Workspace views should continue to call services/builders, not perform formulas or provider calls.

## Source Of Truth Review

| Business object | Authoritative model | Authoritative service | Mutators | Readers |
| --- | --- | --- | --- | --- |
| Accounting integration | `AccountingIntegration` | Settings views plus connector/service boundaries | Settings UI/services | Workspace/settings/accounting services |
| Merit dimension cache | `AccountingDimension` | `AccountingDimensionSyncService`, `AccountingDimensionValueService` | Accounting services | Project code allocation, Projects UI |
| GL data | GL cache models | `GeneralLedgerSyncService` | Accounting sync service only | Financial aggregation/reporting/alerts |
| Project financial totals | Aggregation DTO/result | `ProjectFinancialAggregationService` | No direct mutation; derived read model | Workspace, alerts, allocation services |
| Management allocations | Cost pool/rule/period/version/entry models | Management allocation services | Allocation services and review UI | Project financial management views |
| Financial alerts | Financial alert models | `FinancialAlertEvaluationService` and alert lifecycle services | Alert services/UI actions | Alerts UI, Project Workspace, dashboards |
| E-mail messages | `EmailMessage` | `EmailImportService` | Import/sync only | Inbox, knowledge, communication intelligence |
| Project links from e-mail | `EmailProjectLink` | `EmailProjectLinkService` and suggestion service | Communication services/UI actions | Inbox, Reviews, ProjectKnowledgeBuilder |
| Questions from e-mail | `EmailQuestion` now; future ProjectQuestion | Detection/review services | Communication services | Inbox, Reviews, ProjectKnowledgeBuilder |
| Answer drafts | `EmailAnswerDraft` | `EmailAnswerDraftService` | Draft/review UI via service | Inbox, Reviews, project knowledge |
| Reminder candidates | Future model | Future `ReminderCandidateService` | Reminder service/review UI | Reviews, Project Workspace |
| Documents | `Document` and versions | `DocumentStorageService`, `DocumentStatusService` | Document services | Workspace, knowledge, financial/document flows |
| Audit | `AuditEvent` | `AuditService` | Services only | Knowledge, audit UI, diagnostics |

## Lifecycle Review

| Lifecycle | Status | Compatibility notes |
| --- | --- | --- |
| FinancialAlert | detected/open, acknowledged, dismissed, resolved/reopened concepts. | Strong. Separate detection and notification. |
| ManagementAllocation | draft proposal, edit, approve, immutable approved version, revise/supersede. | Strong. Separate from Merit data. |
| Communication project link | suggested, confirmed, rejected, corrected. | Good. Future generic link should preserve current states. |
| Communication candidate | pending_review, approved, edited, rejected, duplicate, merged, expired. | Proposed only. Align with Review terminology later. |
| Project task/question/decision | Not canonical yet. | Needs architecture before implementation. |
| Reminder candidate | pending_review, approved, snoozed, dismissed, sent, failed, cancelled. | Proposed only. Must stay separate from delivery. |
| Document | document status separate from workflow state. | Strong. |
| Workflow | definition, instance, event. | Strong. Does not own business object status. |
| AuditEvent | append-only. | Strong. |

## AI Consistency Review

AI rules are consistent:

- AI never owns business truth.
- AI output is suggestion, extraction, draft, explanation or evidence.
- Human approval remains authoritative for operational records.
- Knowledge/context builders control AI context.
- Prompt/model/rule versions must be recorded for reproducibility.
- Feedback is structured and versioned.
- Unverified AI guesses must not become learning rules.
- External actions such as e-mail sending, accounting writes and report distribution require policy and human approval.

No architecture document reviewed intentionally bypasses human review for high-risk actions. The risk is future implementation ambiguity, not current architecture contradiction.

## Roadmap Consistency Review

Roadmap strengths:

- It keeps legacy stabilization and Django migration principles.
- It now includes financial and communication-intelligence follow-ups.
- It preserves explicit follow-up around Merit project status/Dimension behavior.

Roadmap weaknesses:

- It still says "Current implementation phase: Platform Core" even though many Workspace, communication, financial, alert and allocation features exist.
- "Current implementation focus: End-to-End Email Processing" is stale relative to recent financial and alert work.
- Some architecture documents have MVP path sections that list already-implemented tasks.
- Financial reporting architecture lists `MVP-FIN-002 Financial Alerts and Review UI`, but current implemented naming has `MVP-FIN-004 Financial Alerts List and Project UI` plus `MVP-FIN-002 Organization Financial Dashboard`.

Recommended correction: make ROADMAP a concise current-state file with one canonical current implementation line and move historical task lists into a changelog or completed-work section.

## Naming Review

Recommended canonical names:

- Operations Workspace Platform: full product name.
- Workspace: whole user-facing product surface.
- Dashboard: one Workspace area.
- Project Workspace: project detail/context area.
- EmailMessage: local synchronized e-mail message.
- EmailThread: e-mail-specific thread.
- Conversation: future cross-channel business conversation.
- EmailProjectLink: current e-mail-to-project link model.
- CommunicationProjectLink: future generic cross-channel link if needed.
- CommunicationIntelligenceCandidate: future communication suggestion record.
- ReminderCandidate: proposed reminder before delivery.
- ReminderDelivery: actual send/delivery record.
- Notification: in-app/system notification, not the same as reminder or alert digest.
- Evidence: source support; qualify domain-specific evidence when persisted.
- Candidate: always qualified by domain.
- Review: human validation pattern; avoid assuming one universal model too early.
- Run: qualify as sync run, evaluation run or intelligence run until platform job/run architecture exists.

## Recommended Corrections

1. Mark `ARCHITECTURE.md`, `ARCHITECTURE_REVIEW.md` and `SPECIFICATION.md` as legacy/prototype references, with `PLATFORM_ARCHITECTURE.md` and `MASTER_ARCHITECTURE.md` as current platform references.
2. Add a future Project Work Architecture document before implementing ProjectTask, ProjectQuestion, ProjectDecision or ProjectRisk.
3. Add a future Notification and Delivery Architecture document before financial alert digest, reminder sending, report delivery or outbound communication services.
4. Add a status/lifecycle glossary to `MASTER_ARCHITECTURE.md` or a separate architecture glossary document.
5. Consolidate roadmap current-state labels and remove stale "current implementation focus" lines.
6. Update older MVP path sections when touched, especially Communication and Financial Reporting task names.
7. Define whether Review remains a Workspace pattern or becomes a shared persisted model after candidate/reminder work begins.
8. Define a common evidence vocabulary under Knowledge architecture before adding more candidate/review models.
9. Define run/job vocabulary before adding more sync/evaluation/intelligence run models.

## Recommended Merges

- Merge `ProjectCommunicationLink` terminology into `CommunicationProjectLink` as the future generic term, while preserving `EmailProjectLink` as current implementation.
- Merge generic "AI review" language into "Reviews" or "Communication Review" to avoid suggesting an AI-owned review queue.
- Merge "Reminder sending", "alert digest", "report delivery" and "outbound e-mail" concepts under a future delivery/notification boundary.
- Treat `Knowledge Evidence`, communication evidence and financial evidence as one vocabulary with domain-specific source references.

## Recommended Service Ownership

Keep services narrow and authoritative:

- Aggregation services calculate facts.
- Policy/evaluation services decide whether facts require attention.
- Review services record human decisions.
- Delivery services perform external side effects only after approval.
- Knowledge builders assemble read-only context.
- Connectors talk to external systems.
- Workspace views orchestrate user requests through services and render results.

No future service should own more than one of these layers unless it is explicitly an orchestrator with no hidden formulas or external side effects.

## Recommended Future Implementation Order

1. Architecture cleanup: glossary, roadmap current-state cleanup, legacy document labels.
2. Project Work Architecture: task/question/decision/risk lifecycle.
3. Review Queue Architecture: shared review patterns and status language.
4. Communication candidate extraction using existing e-mail storage and `EmailProjectLink`.
5. Project work-item implementation.
6. Notification and Delivery Architecture.
7. Reminder candidate engine without delivery.
8. Human approval/snooze UI.
9. Approved outbound delivery.
10. Financial alert scheduled evaluation.
11. Financial alert digest only after delivery architecture and recipient policy.
12. Report snapshot/distribution architecture and implementation.

## Architecture Debt

- Legacy invoice/prototype documents still sit beside current platform architecture without strong labeling.
- `MASTER_ARCHITECTURE.md` contains broad future concepts that are directionally right but not always aligned to latest implemented terminology.
- Roadmap is carrying too much current-state and completed-work detail.
- There is no central glossary for entity names and lifecycle statuses.
- Review, reminder, notification, delivery and run concepts are spread across several documents.
- Global Party/Contact identity remains future while ProjectParty is in active use.

## Potential Risks

- A future implementation could create duplicate task/question/decision models if Project Work Architecture is skipped.
- A future notification feature could accidentally send financial or communication reminders without a shared delivery policy.
- Multiple run models could make operations hard to monitor if no common observability vocabulary is defined.
- Evidence may become inconsistent if each domain invents its own evidence schema.
- ROADMAP drift could make the next implementation task target stale architecture.
- Older invoice-specific documents could confuse new contributors unless marked as historical.

## ADR Assessment

No new ADR is required from this review. The review did not discover a platform-wide contradiction that needs an immediate decision. Existing ADRs already cover the key principles: Organization root, Project as primary context, Communication as first-class domain, Knowledge as AI context, service boundaries, human approval, Merit source-of-truth, management allocations separate from GL cache, financial alerts as lifecycle records, and communication intelligence extending e-mail storage.

## Validation Notes

This review intentionally recommends architecture corrections only. It does not make code, model, service, migration, UI or test changes.

Documentation links referenced from this file should resolve to existing Markdown files. The feature index document is absent and was not created.
