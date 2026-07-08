# Merit Integration Architecture

## 1. Vision

Operations Workspace Platform manages operational project context.

Merit Aktiva remains the accounting system.

The two systems must stay synchronized through explicit, auditable integrations. Workspace helps users create, detect, review, and explain project context, while Merit remains the source for accounting records, accounting dimensions, and official bookkeeping workflows.

The integration must not blur responsibility:

- Workspace owns operational context, project memory, communication, documents, workflow, review, and evidence.
- Merit owns accounting entries, financial reporting, accounting dimensions, and accounting state.
- Synchronization is performed through integration services and connectors, not hidden model side effects.
- User approval is required for accounting-impacting actions unless a future Policy Layer explicitly allows automation.

## 2. Core Concepts

### Merit Integration

The integration boundary between Workspace and Merit Aktiva. It includes configuration, connector code, sync services, conflict handling, audit events, and future UI for review and approval.

### Merit Company

The company/accounting environment inside Merit that corresponds to a Workspace Organization. The MVP should assume one primary Merit company per Organization.

### Merit API Connector

The provider-specific adapter responsible for Merit API calls. It handles request signing, endpoint calls, response parsing, safe retries where appropriate, and sanitized error handling. It must not contain Workspace business decisions.

### Merit Dimension

An accounting dimension in Merit. For the first integration phase, Merit dimensions represent project codes.

### Project Code

The Workspace `Project.code` value. It is the primary project identifier used across communication, documents, accounting, project memory, and future AI reasoning.

### Project Dimension

The Merit dimension corresponding to a Workspace project.

```text
Workspace Project.code <-> Merit Dimension.code
Workspace Project.name <-> Merit Dimension.name
```

### Sync State

The recorded state of Merit synchronization. Examples: `never_synced`, `synced`, `pending_create`, `pending_update`, `conflict`, `failed`, `archived`.

### Conflict

A mismatch or uncertainty between Workspace and Merit. Conflicts should be explicit review objects in the future, not silent overwrites.

### User Approval

The explicit user confirmation required before creating or changing Merit-side accounting dimensions or sending accounting data. Approval must be recorded through AuditEvent and future DomainEvent/WorkflowEvent where relevant.

## 3. Project Code Principle

Workspace `Project.code` should correspond to Merit `Dimension.code`.

```text
Project 26124 Kanarbiku
<->
Merit Dimension 26124 Kanarbiku
```

This makes project context readable across e-mails, documents, invoices, project timelines, Merit accounting dimensions, bank/payment matching, and future AI recommendations.

The code must be stable. Renaming a project should not casually change the project code.

## 4. Merit Dimension Sync

Initial sync direction:

```text
Merit -> Workspace
```

Purpose:

- import existing Merit dimensions
- know which project codes have already been used
- prevent duplicate project codes
- support historical projects that already exist in accounting
- detect Merit-side name/code changes
- prepare reliable invoice export with dimensions later

The first sync should be read-only. It should not create Workspace Projects automatically unless a user later approves that action.

The synced cache should preserve Merit dimension identifier, code, name, active/archived state if available, last synced timestamp, raw metadata for debugging, sync status, and conflict status if detected.

## 5. Workspace Project Creation

Target flow:

```text
User wants new project
-> Workspace checks existing local projects
-> Workspace checks synced Merit dimensions
-> Workspace proposes next available code
-> User confirms
-> Workspace creates Project
-> Workspace creates Merit dimension if missing
-> AuditEvent is recorded
```

Project creation must remain service-driven. The Project model should stay thin and must not call Merit directly.

Recommended service boundary:

```text
ProjectCreationService
-> ProjectCodeAllocationService
-> MeritDimensionSyncService / MeritDimensionService
-> AuditService
```

If Merit is unavailable, Workspace may still create a Project only if the user explicitly chooses a local-only path and the resulting sync state is visible.

## 6. Next Available Project Code

The system should detect numeric project codes and suggest the next free code.

```text
26124 exists
26125 exists
26126 free
-> suggest 26126
```

The allocation service should check both existing Workspace projects and synced Merit dimensions.

Rules:

- numeric codes are compared numerically, not lexically
- non-numeric codes are preserved but excluded from automatic next-code calculation
- suggested code remains a proposal until user approval
- code reservation should later be transactional to avoid concurrent duplicate creation

## 7. Conflict Handling

Conflicts must be visible and auditable.

### Code Exists in Workspace but Not Merit

Possible causes include local project creation before Merit sync, failed Merit dimension creation, or a deleted/archived Merit dimension.

Possible actions: create Merit dimension after user approval, mark as local-only, archive, or correct the Workspace project.

### Code Exists in Merit but Not Workspace

Possible causes include historical accounting dimensions, project creation directly in Merit, or incomplete Workspace import.

Possible actions: create Workspace Project from Merit dimension after user approval, keep as Merit-only historical dimension, or map to an existing Workspace project.

### Same Code, Different Name

Example:

```text
Workspace: 26124 Kanarbiku
Merit:     26124 Kanarbiku tee
```

Possible actions: accept Merit name, keep Workspace name, update Merit dimension, or store alias/metadata. All actions need user approval.

### Same Name, Different Code

This may indicate duplicate project creation or ambiguous naming. Possible actions include manual merge/match, keeping both with explanation, renaming one side, or rejecting proposed sync.

### Merit API Unavailable

Workspace should show a clear non-secret error, record AuditEvent, keep local sync state unchanged or mark failed, and allow retry later.

### User Tries Manual Duplicate Code

The service should prevent duplicate Workspace project codes inside the same Organization and warn if the code already exists in synced Merit dimensions.

## 8. User Approval

Creating or changing Merit dimensions requires explicit user approval unless a future Policy Layer allows automation.

Approval should show the proposed Workspace project, proposed Merit dimension, code, name, evidence, conflict warnings, and expected external API action.

Future automation may be allowed only when policy permits it, confidence is high, no conflict exists, accounting risk is low, and the action is fully auditable.

## 9. Audit

Every sync/create/update/conflict must record AuditEvent.

Examples:

- `merit.dimension_sync_started`
- `merit.dimension_sync_completed`
- `merit.dimension_sync_failed`
- `merit.dimension_conflict_detected`
- `merit.dimension_create_requested`
- `merit.dimension_created`
- `merit.dimension_create_failed`
- `merit.project_code_suggested`
- `merit.project_code_approved`

Audit metadata should include organization, actor where available, Merit integration account, Workspace project id/code where available, Merit dimension id/code where available, sanitized request/response summary, conflict details, and user decision.

Secrets, API keys, signatures, and raw tokens must never be logged.

## 10. Integration Boundaries

Workspace must not hide Merit logic inside the Project model.

Use integration services/connectors:

```text
Project service
-> Integration service boundary
-> Merit connector
-> Merit API
```

Allowed:

- Project service calls a Merit integration service through an explicit interface.
- Merit integration service records AuditEvent.
- Merit connector performs API communication.

Not allowed:

- Project model calling Merit API in `save()`
- template calling Merit connector
- view embedding Merit request logic
- silent Merit dimension creation as a side effect of editing a Project

## 11. Future Accounting Flow

Future invoice-to-Merit flow:

```text
Purchase invoice
-> Project code detected
-> Dimension assigned
-> User confirms
-> Invoice exported to Merit with dimension
```

The project dimension assignment should be evidence-based. Evidence may include project code on invoice line, e-mail project link, supplier history, user-confirmed project context, document metadata, and previous invoice patterns.

Before export, the user should see invoice header, invoice lines, assigned project/dimension per line where relevant, confidence/evidence, Merit payload preview, warnings, and conflicts.

## 12. Security

Merit API credentials must not be stored in plain text.

Future implementation should use secret management suitable for deployment: encrypted secret storage, environment-backed secret injection, provider-specific credential vault, and rotation support.

Rules:

- no API keys in Git
- no API keys in tests
- no tokens in logs
- no secrets in AuditEvent metadata
- integration settings are Organization-scoped
- users need permission to run sync or create Merit dimensions

## 13. MVP Path

Recommended sequence:

1. `MERIT-001` MeritIntegrationConfiguration
2. `MERIT-002` MeritDimension model/cache
3. `MERIT-003` MeritDimensionSyncService
4. `MERIT-004` ProjectCodeAllocationService
5. `MERIT-005` Create Project with Merit Dimension
6. `MERIT-006` Merit conflict review UI
7. `MERIT-007` Export invoice to Merit

Each step should be small, tested, and committed separately.

## 14. Non-goals

Do not implement in this architecture task:

- full accounting sync
- invoice export
- payment sync
- automatic dimension creation without approval
- direct Merit logic inside Project model
- background sync jobs
- scheduled sync
- secret storage implementation
- UI for conflict resolution

This document defines the integration direction. Implementation must follow in separate, small tasks.
