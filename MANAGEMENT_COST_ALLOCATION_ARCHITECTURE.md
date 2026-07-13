# Management Cost Allocation Architecture

This document designs the management cost allocation layer for the Operations Workspace Platform.

It follows `FINANCIAL_REPORTING_ARCHITECTURE.md`, `EMAIL_STORAGE_ARCHITECTURE.md`, `MERIT_INTEGRATION_ARCHITECTURE.md`, `PROJECT_ARCHITECTURE.md`, `SETTINGS_ARCHITECTURE.md`, `ENGINEERING_GUIDE.md`, `DECISIONS.md`, and `ROADMAP.md`.

## 1. Vision

Merit remains the accounting source of truth.

Workspace imports and caches Merit general-ledger data, but it must not rewrite, reclassify, or modify that synchronized accounting data. Management cost allocation is a separate internal reporting layer on top of synchronized GL data and project financial aggregation.

The goal is to let management allocate indirect company costs to projects for internal profitability reporting while preserving the original accounting facts.

```text
Merit GL
  -> Workspace GL Cache
  -> Project Financial Aggregation
  -> Management Cost Allocation Layer
  -> Final Management Project Result
```

The allocation layer must always be reversible, traceable, versioned, and clearly separate from direct accounting costs.

## 2. Architecture And Duplication Review

Existing objects and services remain authoritative:

- `AccountingGLBatch`, `AccountingGLEntry`, and `AccountingGLAllocation` remain the synchronized Merit GL cache.
- `AccountingAccountClassification` remains the direct GL account classification configuration.
- `ProjectFinancialAggregationService` remains the direct project financial aggregation service.
- Organization Financial Dashboard and Project Financial Dashboard remain read-side Workspace views.
- `AccountingSyncState` and `AccountingSyncRun` remain accounting sync observability records.
- `Project` remains the project identity.
- `ProjectParty` remains project-scoped people/organization context until a global Party model exists.
- `AuditEvent` remains the compliance and traceability log.

Confirmed boundaries:

- Do not duplicate the GL cache.
- Do not modify synchronized Merit data.
- Do not write allocation results back to Merit.
- Do not treat management allocations as accounting source data.
- Store management allocations separately from `AccountingGLAllocation`.
- Direct financial reporting and management financial reporting must be distinguishable.

## 3. Core Principles

- Management allocations are internal reporting adjustments, not accounting entries.
- Original Merit GL data is immutable from the allocation layer's point of view.
- Allocations are explicit, user-reviewed, and auditable.
- Project selection is explicit; the system must not guess participating projects.
- Approved allocations are immutable; revisions create new versions.
- Only one approved version is active for a pool and month.
- Only one approved version is active for a source and month. A source may be a cost pool or a Workspace Project.
- Every allocated euro must explain its source, strategy, version, approval, and user decision.
- Reports must separate direct cost, allocated-in management cost, allocated-out management cost, and net management allocation.

## 4. Domain Model

### ManagementCostPool

Purpose:

Represents a bucket of indirect or shared costs that may be redistributed to projects.

Examples:

- Office
- Accounting
- Vehicles
- Management
- Project Managers
- Administration
- IT
- Marketing
- Warehouse
- Insurance

Key fields:

- `organization`
- `uuid`
- `name`
- `description`
- `is_active`
- `allocation_strategy`
- `default_configuration`
- `metadata`
- `created_at`
- `updated_at`

Relationships:

- Belongs to an Organization.
- Has many allocation proposals.
- Has many allocation versions.
- May reference configured source accounts or classification categories in future.

Lifecycle:

- Created by financial admin or management user.
- Configured with a default strategy.
- Used to generate monthly proposals.
- Can be deactivated, but historical versions remain.

Future notes:

- Pools may later support account-code rules, department filters, vehicle registers, employee assignments, and custom strategy plugins.

### AllocationPeriod

Purpose:

Represents the monthly reporting period for a pool allocation.

Example:

```text
2026-06
```

Key fields:

- `organization`
- `month`
- `period_start`
- `period_end`
- `is_closed`
- `metadata`

Relationships:

- Used by proposals and versions.
- Aligns with GL aggregation periods.

Lifecycle:

- Derived from a calendar month.
- Used to generate proposals.
- May later be closed to prevent new active versions except through formal reopening.

Future notes:

- The MVP can store month directly on proposals/versions instead of a separate model, but the concept should remain explicit.

### ManagementAllocationProposal

Purpose:

A generated, editable, non-final allocation draft.

Key fields:

- `organization`
- `pool`
- `month`
- `source_amount`
- `strategy`
- `included_projects`
- `excluded_projects`
- `proposal_lines`
- `status`
- `generated_by`
- `generated_at`
- `metadata`

Status examples:

- `draft`
- `edited`
- `ready_for_approval`
- `approved`
- `discarded`

Relationships:

- Belongs to a pool and month.
- Contains proposed allocation lines.
- May produce an approved version.

Lifecycle:

```text
Generated -> Edited -> Ready For Approval -> Approved -> Version Created
Generated -> Discarded
```

Future notes:

- Proposal lines may be stored as JSON for the first MVP or normalized into proposal-line records if editing/drill-down requires it.

### ManagementAllocationVersion

Purpose:

An approved allocation snapshot for one source and month.

Supported source types:

- `cost_pool`: allocates a configured ManagementCostPool.
- `workspace_project`: allocates direct accounting cost from a source Project to other Projects.

Key fields:

- `organization`
- `pool`
- `source_type`
- `source_project`
- `source_amount_basis`
- `source_currency`
- `source_period_start`
- `source_period_end`
- `month`
- `version_number`
- `status`
- `source_amount`
- `strategy`
- `approved_by`
- `approved_at`
- `supersedes_version`
- `is_active`
- `metadata`
- `created_at`

Status examples:

- `approved`
- `superseded`
- `voided`

Relationships:

- For `cost_pool`, `pool` is required and `source_project` must be empty.
- For `workspace_project`, `source_project` is required and `pool` must be empty.
- The same source Project cannot also be a target/recipient Project.

Version identity:

- Cost pool source: `period + pool`.
- Workspace Project source: `period + source_project`.
- Approving a new version supersedes only prior approved versions for the same source/month.

### Workspace Project Allocation Source

Purpose:

Allows direct accounting cost from one Workspace Project to be redistributed internally to other Projects without changing Merit or GL cache data.

Amount basis:

- `project_direct_cost` uses `ProjectFinancialAggregationService` for the exact selected month.
- It reads `ProjectFinancialAggregationResult.total_cost`.
- It excludes management allocations from the source amount.
- It stores source diagnostics, data quality status, period, currency, and selected target traceability in version metadata.

Validation:

- Source Project must belong to the same Organization.
- Source Project cannot be a target Project.
- Mixed-currency project source data requires an explicit currency selection.
- No raw GL summing belongs in Workspace views or templates.

Reporting:

- Recipient Projects receive `management_cost_allocated_in`.
- Source Projects receive `management_cost_allocated_out`.
- Net management allocation is `allocated_in - allocated_out`.
- Management total cost is `direct_cost + allocated_in - allocated_out`.
- Cost pool sources do not create source-project offsets.

- Belongs to one pool and month.
- Has many allocation entries.
- May supersede a prior version.
- Only one active version should exist per pool/month.

Lifecycle:

```text
Proposal Approved -> Version v1 Active
Revision Approved -> Version v1 Superseded -> Version v2 Active
```

Future notes:

- Approved versions must be append-only. Corrections create new versions rather than mutating approved entries.

### ManagementAllocationEntry

Purpose:

One approved allocation line assigning part of a pool/month amount to one project.

Key fields:

- `organization`
- `version`
- `pool`
- `month`
- `project`
- `percentage`
- `allocated_amount`
- `currency`
- `reason`
- `manual_override`
- `locked`
- `created_by`
- `created_at`
- `metadata`

Relationships:

- Belongs to an approved version.
- Links to one Project.
- Can be traced back to pool, strategy, and source evidence.

Lifecycle:

- Created when a version is approved.
- Immutable after approval.
- Superseded indirectly when a later version becomes active.

Future notes:

- Entries should support drill-down to source GL accounts, account classifications, source period, and proposal evidence.

## 5. Entity Relationships

```text
Organization
  -> ManagementCostPool
      -> ManagementAllocationProposal
      -> ManagementAllocationVersion
          -> ManagementAllocationEntry
              -> Project

AccountingGLBatch
  -> AccountingGLEntry
      -> AccountingGLAllocation
          -> ProjectFinancialAggregationService
              -> Direct Project Result

Direct Project Result
  + Active ManagementAllocationEntry
  -> Management Project Result
```

Important separation:

```text
AccountingGLAllocation != ManagementAllocationEntry
```

`AccountingGLAllocation` is synchronized accounting evidence from Merit. `ManagementAllocationEntry` is an internal management reporting decision.

## 6. Allocation Strategies

The architecture must support pluggable allocation strategies. A strategy calculates a proposal; it does not approve it.

Initial strategies:

- Revenue proportional
- Equal split
- Manual percentage
- Manual amount
- Project manager projects

Future strategies:

- Hours
- Budget
- Headcount
- Area
- Vehicle usage
- Employee timesheet
- Procurement volume
- Custom plugin

Strategy interface concept:

```text
AllocationStrategy.generate(
    pool,
    month,
    source_amount,
    selected_projects,
    configuration,
    evidence
) -> AllocationProposal
```

Rules:

- Strategy output must sum to 100 percent or the full source amount.
- Rounding differences must be explicit.
- Manual overrides must be marked.
- Strategy must not select projects silently.
- Strategy must not mutate source GL rows.

## 7. Project Selection

The system never guesses which projects participate.

Users explicitly select:

- included projects;
- excluded projects;
- optionally locked projects that should keep a fixed percentage or amount during edits.

Possible project selection helpers may suggest candidates from:

- projects with revenue in the month;
- projects with direct costs in the month;
- active projects;
- projects managed by a selected ProjectParty or future Party role;
- manually saved pool defaults.

These helpers are suggestions only. The final participating project list is a user decision and must be auditable.

## 8. Generation Flow

```text
User selects pool
  -> User selects month
  -> User selects participating projects
  -> User selects allocation strategy
  -> System reads direct financial aggregates and source pool amount
  -> System calculates draft proposal
  -> Proposal shows amounts, percentages, evidence, and warnings
  -> User edits proposal
  -> User submits for approval
```

Generation service boundary:

```text
ManagementAllocationProposalService
  -> reads ProjectFinancialAggregationService
  -> reads AccountingGL cache/classifications where needed
  -> calls allocation strategy
  -> creates proposal
  -> records AuditEvent
```

The service must not call Merit API directly and must not write accounting cache records.

## 9. Editing Flow

Users may:

- change percentages;
- change amounts;
- remove projects;
- add projects;
- lock project rows;
- add reasons;
- mark manual overrides.

The proposal must remain balanced:

- percentage proposals total 100 percent;
- amount proposals total the source amount;
- rounding differences are shown as a separate adjustment or assigned through an explicit rule.

Editing rules:

- Draft proposals are mutable through service methods.
- Approved versions are immutable.
- Every meaningful edit records who changed what and why.

## 10. Approval Flow

```text
Proposal ready for approval
  -> User reviews source amount, projects, percentages, warnings
  -> User approves
  -> Active prior version is superseded
  -> New immutable version is created
  -> Version entries are created
  -> AuditEvent records approval
  -> Reports use new active version
```

Approval must require a user action. No automatic approval is allowed in the initial implementation.

Approval service boundary:

```text
ManagementAllocationApprovalService
  -> validates proposal balance
  -> validates selected projects
  -> supersedes prior active version
  -> creates new active version and entries
  -> records AuditEvent
```

## 11. Revision Flow

Approved allocations may later be revised.

Example:

```text
Office June v1 approved
  -> management reviews updated office cost
  -> v2 proposal generated from v1
  -> user edits
  -> v2 approved
  -> v1 superseded
  -> reports use v2
  -> audit still shows v1
```

Revision rules:

- Do not mutate approved entries.
- Create a new proposal from the active version or from current strategy.
- New version supersedes the prior active version after approval.
- Historical reports can optionally show "as originally approved" versus "current active version".

## 12. Reporting Integration

Project Financial Summary should evolve from:

```text
Revenue
Direct Cost
Result
Margin
```

to:

```text
Direct Revenue
Direct Cost
Direct Result
Allocated Management Cost
Management Result
Management Margin
```

Definitions:

- Direct Revenue: revenue from synchronized GL/project allocations.
- Direct Cost: direct project costs from synchronized GL/project allocations.
- Direct Result: direct revenue minus direct cost.
- Allocated Management Cost: active approved management allocation entries for the project and period.
- Management Result: direct result minus allocated management cost.
- Management Margin: management result divided by direct revenue where revenue is non-zero.

Reports must clearly label:

- direct accounting data;
- internal management allocation;
- version used;
- allocation pool;
- source period;
- data-quality warnings.

## 13. Traceability

Every allocated euro must explain:

- origin pool;
- origin GL accounts or source amount basis;
- allocation strategy;
- included/excluded projects;
- proposal;
- approved version;
- approval date;
- approving user;
- manual override reason;
- active/superseded status.

Drill-down path:

```text
Project Management Result
  -> Allocated Management Cost
  -> ManagementAllocationEntry
  -> ManagementAllocationVersion
  -> ManagementCostPool
  -> Source GL accounts / classifications / period
  -> AuditEvent
```

## 14. Audit Model

Audit events required:

- pool created;
- pool configuration changed;
- proposal generated;
- proposal edited;
- project added to proposal;
- project removed from proposal;
- manual override applied;
- proposal discarded;
- proposal approved;
- version activated;
- prior version superseded;
- version voided, if later supported.

Audit metadata should include:

- organization id;
- pool id;
- month;
- proposal id;
- version id;
- previous version id;
- affected project ids;
- strategy;
- source amount;
- before/after summary;
- reason.

Secrets, raw external API payloads, and credential-bearing URLs must never be stored in allocation audit metadata.

## 15. API Boundaries

Allowed dependencies:

- management allocation services may read `ProjectFinancialAggregationService`;
- management allocation services may read GL cache and account classifications;
- reporting services may read active management allocation versions;
- Workspace views call management allocation services.

Forbidden dependencies:

- no direct Merit API calls from allocation services;
- no writes to `AccountingGLBatch`, `AccountingGLEntry`, or `AccountingGLAllocation`;
- no direct model mutation from templates or views;
- no hidden automatic approval;
- no project selection without user confirmation.

## 16. UI Boundaries

Workspace UI areas:

- Management Cost Pools settings;
- monthly allocation proposal screen;
- proposal editor;
- approval review screen;
- version history screen;
- project financial report allocation drill-down;
- organization financial dashboard management result view.

UI rules:

- Views remain thin.
- Forms validate user intent and call services.
- UI must show direct costs and allocated costs separately.
- UI must show proposal totals, rounding differences, and warnings before approval.
- UI must show active version and allow version history drill-down.
- UI must never imply management allocations changed Merit.

## 17. Service Boundaries

Suggested future services:

- `ManagementCostPoolService`
- `ManagementAllocationProposalService`
- `ManagementAllocationEditingService`
- `ManagementAllocationApprovalService`
- `ManagementAllocationRevisionService`
- `ManagementAllocationReportingService`
- `ManagementAllocationTraceabilityService`

Service rules:

- Builders/read services can assemble reporting context.
- Write services create proposals, edits, versions, and audit events.
- Strategy classes calculate proposed splits only.
- Approval service owns version activation.
- Reporting service combines direct project aggregates with active management allocation entries.

## 18. Data Quality And Controls

Warnings required:

- proposal source amount is zero;
- proposal has no projects;
- proposal total does not equal source amount;
- proposal percentage does not equal 100 percent;
- project has no direct revenue but receives allocation;
- source GL sync is missing or failed for the month;
- account classification is incomplete;
- active version is superseded;
- mixed currencies are present.

Controls:

- no approval if proposal is unbalanced;
- no approval if selected projects are empty;
- no approval if required reason is missing for manual overrides;
- no silent currency conversion;
- no automatic allocation to archived projects without explicit confirmation.

## 19. Allocation Wizard And Preview

Management allocation creation uses a guided Workspace wizard rather than one dense form. Wizard state is presentation state only: it is scoped to the user's session, contains no secrets, and creates no database records until the final draft confirmation.

Wizard steps:

1. Source.
2. Period and source amount.
3. Recipient Projects.
4. Allocation preview.
5. Create draft.

`ManagementAllocationProposalService` remains the authoritative proposal engine. The read-only `preview()` operation and the write-side `generate()` operation share the same calculation helper so previewed proposed entries match persisted draft entries when source data is unchanged.

Preview purity rules:

- Preview creates no `ManagementAllocationPeriod`, `ManagementAllocationVersion`, `ManagementAllocationEntry`, or `AuditEvent`.
- Preview does not mutate GL cache rows, Projects, cost pools, or allocation source records.
- Preview does not call Merit or any external accounting API.
- Preview shows source diagnostics, warnings, balancing, proposed recipient amounts, and before/after management cost impact.
- Draft creation happens only after explicit final confirmation.

Preview freshness is tracked with a deterministic fingerprint derived from source identity, period, source basis, source amount, strategy, recipients, manual values, currency, and proposed entries. Final draft creation rebuilds the proposal command from server-side wizard state and verifies the latest preview fingerprint where practical. If source data or wizard inputs changed, the user must refresh preview before creating a draft.

Existing approved allocation visibility:

- Preview warns when a current approved version exists for the same source/month.
- Creating a draft does not supersede approved history.
- Superseding happens only when a later draft is explicitly approved.

Existing draft visibility:

- Preview warns when another draft exists for the same source/month.
- The platform does not silently resolve duplicate drafts.
- Users review existing drafts through normal allocation lifecycle screens.

## 20. Security And Permissions

Future permissions:

- `financial_admin`: configure pools, generate, edit, approve, revise.
- `management`: review and approve management reports.
- `accountant`: review source amounts and classifications.
- `project_manager`: view allocation impact for own projects if policy allows.
- `project_viewer`: no access to company-wide allocation configuration by default.

Management allocation screens expose company overhead, salaries, administration, and margin impact. They require stronger permissions than normal project detail pages.

## 21. Migration Strategy

Initial implementation path:

1. Architecture document.
2. Management allocation Django app or accounting subdomain decision.
3. `ManagementCostPool` model.
4. Proposal DTO/service without persistence, using test data.
5. Proposal persistence.
6. Approval/version models.
7. Project financial reporting integration behind a feature flag or explicit view mode.
8. Workspace UI for pools and proposals.
9. Version history and drill-down.
10. Dashboard management result columns.

Migration rules:

- Existing GL cache remains untouched.
- Existing direct project financial aggregation remains valid.
- Management reporting should be additive and opt-in at first.
- Historical allocations start empty; do not infer prior months automatically.

## 22. Future Compatibility

Architecture must support:

- Budget vs Actual;
- Forecast;
- Cash Flow;
- Procurement Analytics;
- Financial Alerts;
- Project profitability;
- Department profitability;
- Employee profitability;
- project manager portfolio profitability;
- allocation simulations;
- allocation snapshots in monthly reports.

## 23. Non-Goals

Do not implement in the initial architecture or first model tasks:

- Merit write-back;
- GL modification;
- automatic project selection;
- AI allocation;
- budgeting;
- forecasting;
- payroll integration;
- time tracking integration;
- external report distribution changes.

## 24. Future Roadmap

Suggested tasks:

1. `COST-ALLOC-001` Management Cost Pool model.
2. `COST-ALLOC-002` Allocation Strategy interface and DTOs.
3. `COST-ALLOC-003` Allocation Proposal generator.
4. `COST-ALLOC-004` Proposal editing service.
5. `COST-ALLOC-005` Allocation Version and Entry models.
6. `COST-ALLOC-006` Approval and revision services.
7. `COST-ALLOC-007` Project Financial Aggregation integration.
8. `COST-ALLOC-008` Workspace Cost Pool settings UI.
9. `COST-ALLOC-009` Proposal review and approval UI.
10. `COST-ALLOC-010` Project financial management result view.

## 25. Engineering Rules

- GL cache is read-only for management allocation.
- Approved allocation versions are immutable.
- Revisions create new versions.
- Service layer owns generation, editing, approval, and reporting integration.
- Strategies are pluggable and deterministic.
- Project participation is always user-confirmed.
- Audit is required for every important action.
- Direct and allocated costs must remain visibly separate in reports.
- Wizard preview must remain read-only and share calculation logic with final proposal generation.
