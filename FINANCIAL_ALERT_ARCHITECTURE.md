# Financial Alert Architecture

This document designs the architecture for detecting, storing, reviewing, resolving, and later distributing project financial alerts in the Operations Workspace Platform.

It follows `FINANCIAL_REPORTING_ARCHITECTURE.md`, `MANAGEMENT_COST_ALLOCATION_ARCHITECTURE.md`, `PROJECT_ARCHITECTURE.md`, `PLATFORM_ARCHITECTURE.md`, `EMAIL_STORAGE_ARCHITECTURE.md`, `ENGINEERING_GUIDE.md`, `DECISIONS.md`, `ROADMAP.md`, and `README.md`.

This is an architecture document only. It does not introduce models, migrations, services, commands, UI, scheduled jobs, or e-mail delivery.

## 1. Executive Summary

A Financial Alert is a persisted lifecycle record that says a financially relevant project condition was detected and needs visibility, review, acknowledgement, resolution, or dismissal.

Examples:

- A Project lifetime result is negative.
- A Project current-month result is negative.
- A Project has no project revenue recorded for the current month.

Financial alerts are persisted rather than calculated only during page rendering because alerts are operational work items. Users need to know when a condition was first detected, whether it was acknowledged, whether it later resolved, whether it was dismissed intentionally, and whether it returned after resolution. A rendered calculation alone cannot provide lifecycle, accountability, deduplication, or notification readiness.

Financial fact and alert policy are separate:

- A financial fact is the result of authoritative financial aggregation, such as current-month management result or lifetime accounting result.
- An alert policy decides whether that fact should create, update, resolve, or reopen an alert.

Detection and notification are also separate:

- Alert evaluation determines and persists current alert state.
- Notification selection decides which persisted alerts should be sent.
- Delivery sends e-mail or future channels.

No Merit or e-mail API call should happen during normal alert listing. Alerts are organization- and project-scoped. Historical alerts are retained, not hard-deleted.

## 2. Architecture Position

Financial alert flow:

```text
Merit GL
  -> local GL cache
  -> direct financial aggregation
  -> management allocation integration
  -> financial facts
  -> alert evaluation
  -> persisted alert records
  -> Alerts UI / Project UI
  -> later weekly e-mail digest
```

Alert evaluation reads existing local financial services:

- `ProjectFinancialAggregationService` for accounting/direct financial facts.
- `ProjectManagementFinancialService` for management financial facts when management basis is selected.
- Accounting sync state/read models for source freshness and data quality context.
- Management allocation versions/entries only through the management financial service boundary where practical.

Alert evaluation must not calculate financial truth independently. It must not modify synchronized GL cache, Project records, accounting integrations, management allocation records, or source documents. It opens, updates, resolves, or dismisses alert lifecycle records only through explicit alert services.

## 3. Fact Vs Policy

Facts are observed values from authoritative financial services.

Examples:

- monthly management result = `-2450 EUR`
- lifetime accounting result = `-8100 EUR`
- current-month revenue = `0 EUR`
- source GL sync completed at `2026-07-14T08:30:00`
- unclassified amount = `310 EUR`

Policies decide what to do with facts.

Examples:

- create a warning when current-month management result is below `0`;
- create a critical alert when lifetime result is below `-5000`;
- ignore no-revenue alerts until the 10th day of the month;
- evaluate only active Projects for current-month operational alerts;
- evaluate completed Projects for historical lifetime negative alerts.

The architecture must allow policy to evolve without changing source financial calculations. Rules can change threshold, severity, candidate scope, basis, grace period, or suppression behavior while the financial services continue to return the same facts.

## 4. Initial Alert Types

Canonical alert type keys:

- `project_lifetime_negative`
- `project_current_month_negative`
- `project_current_month_no_revenue`

### project_lifetime_negative

Business meaning:

The Project's lifetime result is below the configured threshold, normally below zero.

Calculation basis:

Use lifetime financial aggregation for the Project. Management basis is preferred when approved allocations exist; accounting/direct result remains captured in metadata.

Period semantics:

Lifetime from earliest reliable linked financial activity or Project start date to the evaluation date.

Default severity:

Critical when below a configured critical threshold; otherwise warning or critical based on organization policy. MVP default can be critical for below zero if no threshold is configured.

Candidate Projects:

Active, completed, archived, and other Projects with lifetime financial activity. Do not assume the current calendar year equals lifetime.

Opening condition:

Selected lifetime result is less than threshold, default `0`.

Resolving condition:

Selected lifetime result is greater than or equal to threshold.

Fingerprint scope:

`organization + project + alert_type + basis`

Expected UI text:

`Project lifetime result is negative`

Known limitations:

Lifetime start may be approximate until historical GL backfill, Project start dates, and project linkage quality improve. Mixed-currency Projects may be skipped or marked partial.

### project_current_month_negative

Business meaning:

The Project's current-month result is below the configured threshold, normally below zero.

Calculation basis:

Use current calendar month aggregation. Management basis is preferred; accounting value should be shown for transparency.

Period semantics:

Organization-timezone current month from month start through evaluation date. The month may be incomplete.

Default severity:

Warning. Negative current-month result during an incomplete month should not automatically be critical.

Candidate Projects:

Active Projects and Projects with current-month financial activity. Completed or archived Projects may be excluded unless policy includes them.

Opening condition:

Selected current-month result is less than threshold, default `0`.

Resolving condition:

Selected current-month result is greater than or equal to threshold for the same month.

Fingerprint scope:

`organization + project + alert_type + basis + YYYY-MM`

Expected UI text:

`Current-month project result is negative`

Known limitations:

Current-month data may be incomplete, GL sync may be stale, and unclassified amounts may make the result partial.

### project_current_month_no_revenue

Business meaning:

A Project in scope has zero trusted current-month project revenue recorded.

Calculation basis:

Accounting/direct revenue basis only. Management allocations do not affect revenue detection.

Period semantics:

Organization-timezone current month from month start through evaluation date.

Default severity:

Warning.

Candidate Projects:

Recommended MVP: active Projects with current-month cost or other financial activity and zero revenue. Avoid creating noisy alerts for every Project in the database.

Opening condition:

Current-month trusted direct revenue equals `0` and the Project qualifies for candidate scope.

Resolving condition:

Current-month direct revenue becomes greater than `0`, or the Project no longer qualifies for candidate scope.

Fingerprint scope:

`organization + project + alert_type + YYYY-MM`

Expected UI text:

`No project revenue recorded for current month`

Known limitations:

This is not proof that no invoice was issued. A true invoice-issued alert belongs after Merit sales-invoice synchronization is implemented.

## 5. Accounting Vs Management Basis

Future configurable basis enum:

- `accounting`
- `management`

Recommended defaults:

- `project_lifetime_negative`: management basis preferred when approved allocations exist; include accounting result in metadata for transparency.
- `project_current_month_negative`: management basis preferred; current incomplete month normally warning severity.
- `project_current_month_no_revenue`: accounting/direct revenue basis; management allocations must not affect revenue detection.

The UI must display:

- accounting value;
- management value;
- basis used by the alert;
- source data quality and sync freshness where relevant.

Accounting basis is useful for traceability to Merit-sourced GL. Management basis is useful for internal profitability after approved management allocations. Alerts must make the selected basis explicit so users do not confuse internal management reporting with accounting facts.

## 6. Lifetime Period Semantics

Project lifetime should not mean current calendar year.

Preferred rules:

- Start from earliest linked financial activity when reliable.
- If no linked activity exists, use Project start date where reliable.
- If neither exists, use a conservative lower bound such as the first synchronized accounting period for the Organization and mark the alert data quality as partial.
- End at evaluation date.
- Completed and archived Projects remain evaluable for historical/lifetime alerts.

Missing Project start dates:

- Do not invent a start date.
- Use earliest available linked financial activity when present.
- If the lifetime window is incomplete, store a data-quality warning in alert metadata.
- UI should explain that lifetime result may change when historical sync/backfill improves.

## 7. Current-Month Semantics

Current month is the calendar month in the Organization timezone.

Definitions:

- current month start: first day of the current month in organization timezone;
- evaluation date: date used by the alert run;
- current month end for evaluation: evaluation date, not necessarily calendar month close;
- month may be incomplete;
- no automatic assumption that a negative current month is final.

Alert titles and messages should make the period clear, for example:

`Current-month result is negative for July 2026`

Future grace-period rules:

- suppress before day N;
- lower severity before month close;
- evaluate previous closed month separately;
- escalate if the same condition remains after close.

## 8. No-Revenue Semantics

For MVP, the no-revenue condition is:

- Project has relevant activity or is explicitly in scope;
- current-month trusted direct revenue equals zero.

Do not call this alert `No revenue invoice issued` until sales-invoice import exists. Use `No project revenue recorded for current month` or equivalent.

Candidate-scope options:

- active Projects only;
- active Projects with direct cost/activity in the month;
- Projects explicitly monitored;
- Projects with recent activity;
- Projects with current-month cost but no revenue.

Recommended MVP:

Active Projects with current-month cost or financial activity and zero revenue.

This alert is not proof that no invoice was issued. It only says the Workspace financial aggregation does not currently show project revenue for the selected period.

Future true invoice alert requires:

- Merit sales-invoice cache;
- invoice issue date;
- Project/dimension linkage;
- invoice status;
- invoice synchronization freshness.

## 9. Alert Policy Model

Future concept: `FinancialAlertRule`.

Suggested fields:

- `organization`
- `alert_type`
- `name`
- `is_active`
- `financial_basis`
- `severity`
- `threshold_amount`
- `threshold_percentage`
- `grace_day`
- `project_status_scope`
- `candidate_scope`
- `currency`
- `configuration` JSON
- `created_at`
- `updated_at`

Generic fields:

- organization, alert type, name, active flag;
- basis, severity, thresholds, grace day;
- status/candidate scope;
- currency and configuration;
- timestamps.

Type-specific settings belong in `configuration` where generic fields would become misleading. Examples include lifetime lower-bound behavior, no-revenue candidate activity rules, post-month-close escalation, or data-quality strictness.

Rules must not be hardcoded for one organization. Organization defaults can be seeded later. Future per-project overrides should be layered on top of organization rules without changing the core financial calculations.

No model is implemented in this task.

## 10. Persisted Alert Model

Future concept: `FinancialAlert`.

Suggested fields:

- `organization`
- `project`
- `rule` nullable
- `alert_type`
- `financial_basis`
- `severity`
- `status`
- `fingerprint`
- `title`
- `message`
- `period_start` nullable
- `period_end` nullable
- `currency`
- `accounting_amount` nullable
- `management_amount` nullable
- `evaluated_amount` nullable
- `threshold_amount` nullable
- `first_detected_at`
- `last_detected_at`
- `last_evaluated_at`
- `acknowledged_at` nullable
- `acknowledged_by` nullable
- `resolved_at` nullable
- `dismissed_at` nullable
- `dismissed_by` nullable
- `resolution_reason`
- `metadata` JSON
- `created_at`
- `updated_at`

Source amounts are snapshots for traceability. They explain why an alert was opened or updated at evaluation time. Project financial data remains authoritative and can be recalculated from source read models. Alert fields are not a replacement for financial reporting, drill-down, GL cache, management allocation records, or source documents.

## 11. Status Lifecycle

Statuses:

- `open`
- `acknowledged`
- `resolved`
- `dismissed`

Lifecycle:

```text
not present
  -> open
  -> acknowledged
  -> resolved
```

Optional user path:

```text
open / acknowledged
  -> dismissed
```

Reopen behavior:

```text
resolved
  -> open
```

when the same condition returns.

Clarifications:

- Acknowledged does not mean resolved.
- Dismissed means intentionally suppressed or ignored by a user.
- Dismissed alerts may reopen depending on policy.
- Alerts are never hard-deleted.
- Historical lifecycle timestamps remain available for audit and reporting.

## 12. Fingerprint And Deduplication

Financial alerts require deterministic fingerprints.

Examples:

- Lifetime negative: `organization + project + alert_type + basis`
- Current-month negative: `organization + project + alert_type + basis + YYYY-MM`
- No revenue: `organization + project + alert_type + YYYY-MM`

Requirements:

- repeated evaluation updates the same alert;
- no duplicate open alerts for the same condition;
- resolved alerts may reopen;
- fingerprint generation is deterministic and versioned;
- rule changes may require a rule id or rule version component;
- fingerprint parts should be stable strings, not display labels.

Fingerprint versioning can be stored in metadata or as a prefix, for example `v1:...`. If fingerprint rules change, the migration strategy must decide whether old alerts stay under old fingerprints or are remapped.

## 13. Occurrence And History Design

Two valid options:

Option A:

- one `FinancialAlert` record with lifecycle timestamps and `AuditEvent` for user actions.

Option B:

- `FinancialAlert` as current lifecycle record;
- `FinancialAlertOccurrence` or evaluation history for material transitions.

Preferred scalable design:

- `FinancialAlert` stores current lifecycle state.
- `FinancialAlertOccurrence` or evaluation history stores material transitions such as opened, updated materially, resolved, reopened, dismissed, or severity changed.
- `AuditEvent` records user actions such as acknowledge, dismiss, manual resolve, and rule changes.

MVP boundary:

The full occurrence model may be postponed if lifecycle timestamps, metadata, and `AuditEvent` are sufficient initially. Do not emit duplicate audit events for unchanged daily evaluations.

## 14. Evaluation Engine

Future service: `FinancialAlertEvaluationService`.

Suggested API:

```python
evaluate_project(project, evaluation_date, rule_set=None)
evaluate_organization(organization, evaluation_date, rule_set=None)
```

Responsibilities:

- load applicable alert rules;
- determine eligible Projects;
- call `ProjectFinancialAggregationService`;
- call `ProjectManagementFinancialService` where management basis is needed;
- construct financial facts;
- evaluate conditions;
- open, update, reopen, or resolve alerts;
- return structured evaluation result.

Must not:

- call Merit API;
- send e-mails;
- mutate GL/cache/allocation records;
- duplicate financial formulas;
- evaluate all historical months unless explicitly requested;
- perform hidden policy decisions in templates.

## 15. Evaluation Commands And Results

Future immutable command DTO:

```text
EvaluateFinancialAlertsCommand
  organization
  evaluation_date
  project_ids=None
  alert_types=None
  dry_run=False
  actor=None
  metadata=None
```

Future immutable result DTO:

```text
FinancialAlertEvaluationResult
  evaluated_projects
  evaluated_rules
  opened_count
  updated_count
  reopened_count
  resolved_count
  unchanged_count
  skipped_count
  warnings
  alert_ids
  metadata
```

Dry-run mode:

- calculates proposed changes;
- writes no alert records;
- writes no audit events;
- useful for command-line verification and future admin preview;
- must still use the same fact and policy evaluation path as write mode.

## 16. Evaluation Scheduling

Step 1:

- manual management command;
- optional manual UI action later.

Step 2:

- scheduled daily evaluation;
- weekly digest sends current alerts.

Recommended future cadence:

- daily evaluation;
- weekly e-mail digest.

Alert detection must not be tied only to user page visits. Evaluation should be idempotent, safe to retry, organization-timezone aware, and protected from overlapping runs for the same organization/date. Failed evaluation should be recorded with safe error information and should not leave partial external side effects.

## 17. Evaluation Run Tracking

Future concept: `FinancialAlertEvaluationRun`, unless a generic job/run abstraction exists by then.

Suggested fields:

- `organization`
- `started_at`
- `completed_at`
- `status`
- `evaluation_date`
- `project_count`
- `opened_count`
- `resolved_count`
- `failed_count`
- `safe_error`
- `metadata`

Recommendation:

Use a dedicated alert evaluation run model for the first implementation unless a stable platform-wide job/run abstraction exists. Alerts have domain-specific counters and operational questions that differ from accounting sync runs, but the shape should remain compatible with future generic job observability.

## 18. Severity

Severity enum:

- `info`
- `warning`
- `critical`

Suggested defaults:

- lifetime negative: critical, or threshold-based warning/critical;
- current-month negative: warning;
- current-month no revenue: warning.

Future severity rules:

- critical when negative amount exceeds configurable threshold;
- escalate when unresolved over time;
- reduce severity during incomplete current month;
- downgrade to info for low-risk or already acknowledged conditions.

## 19. Currency Handling

Rules:

- do not compare or aggregate incompatible currencies;
- rule may specify currency;
- mixed-currency Project results generate evaluation warning or skip;
- no currency conversion in alert evaluation;
- alert stores currency used;
- UI shows currency beside every amount.

If a Project has mixed-currency financial data and no explicit currency filter, the evaluator should either skip the alert with a warning or open a partial-confidence data-quality alert, depending on rule policy. Do not silently combine currencies into one trusted amount.

## 20. Data-Quality Handling

Alert evaluation must consider:

- unclassified amounts;
- mixed currencies;
- missing GL sync;
- failed sync;
- no Project links;
- partial aggregation quality;
- draft management allocations;
- missing approved allocation versions.

Recommended behavior:

- do not silently create high-confidence alerts from unreliable totals;
- store `data_quality` and warnings in alert metadata;
- allow low-confidence/partial alerts only when policy explicitly permits;
- skip evaluation when the financial value cannot be trusted enough;
- never treat draft management allocations as approved management results.

Type-specific behavior:

- Lifetime negative: skip or mark partial if lifetime period is incomplete.
- Current-month negative: warning severity is acceptable for incomplete month, but data freshness must be visible.
- No revenue: require a candidate scope that indicates current activity; otherwise skip to avoid noise.

## 21. Sync Freshness

Financial alerts must expose whether source GL data is current enough.

Design:

- evaluation can inspect `AccountingSyncState` and latest `AccountingSyncRun`;
- stale or failed sync does not automatically invalidate all alerts;
- UI must display financial-data freshness;
- future `financial_data_stale` alert type may be added.

Do not invent hidden freshness thresholds. Freshness thresholds belong to rule configuration or organization settings.

## 22. Project Eligibility

Candidate scopes:

- `active`
- `active_and_completed`
- `all_with_activity`
- `selected_projects`
- `projects_with_month_activity`
- `projects_with_cost_but_no_revenue`

Recommended defaults:

- `project_lifetime_negative`: all Projects with lifetime activity, including completed/archived for historical alerts.
- `project_current_month_negative`: active Projects with current-month activity.
- `project_current_month_no_revenue`: active Projects with current-month cost or financial activity and zero revenue.

Archived historical Projects may retain open lifetime alerts. They should not necessarily receive current-month operational alerts unless policy explicitly includes them.

## 23. Resolution Logic

Per type:

Lifetime negative:

- resolve when evaluated result is greater than or equal to threshold.

Current-month negative:

- resolve when selected month result is greater than or equal to threshold.

No revenue:

- resolve when current-month revenue becomes greater than `0`;
- or Project no longer qualifies for candidate scope.

Evaluation updates `last_detected_at` while the condition remains true. `resolved_at` is set only on transition into resolved. User acknowledgement may remain after updates unless policy resets acknowledgement on material value change, severity change, or reopening.

## 24. Dismissal And Suppression

User dismissal requires a reason.

Dismissal may apply:

- permanently to this fingerprint;
- until next evaluation;
- until a specific date;
- until value changes materially.

Recommended MVP:

Dismiss the current fingerprint with reason. The condition returning after resolution or after meaningful value change may reopen depending on policy.

Future:

- `snooze_until`
- rule-level suppression
- Project-level exclusion
- user-specific notification preferences

## 25. Central Alerts Workspace

Future route:

```text
/workspace/alerts/
```

Required filters:

- Project
- month/period
- alert type
- severity
- status
- Project status
- financial basis
- data quality
- search

Default sorting:

- open/acknowledged first;
- critical before warning;
- newest detected first.

Columns:

- alert
- Project
- period
- basis
- accounting value
- management value
- severity
- status
- first detected
- last detected
- actions

Actions:

- open Project
- open Project Financials
- acknowledge
- resolve only when appropriate/manual policy allows
- dismiss with reason

## 26. Project Detail Integration

Project detail should show:

- Alerts tab or panel;
- open alert count badge;
- severity summary;
- latest open alerts;
- link to full filtered Alerts list;
- resolved alert history.

Project Financials should show relevant financial alerts near summary cards. Templates must not contain alert formulas. Templates render alert records and alert context produced by services/builders.

## 27. Dashboard Integration

Future Dashboard integration:

- Dashboard open-alert count;
- Financial Dashboard alert badges;
- negative-result row link;
- costs-without-revenue alert marker.

Do not overload the initial UI. The central Alerts workspace and Project-level visibility are the first product surfaces.

## 28. Audit

Reuse `AuditEvent` for user actions:

- acknowledged;
- dismissed;
- manually resolved;
- manually reopened if supported;
- rule changes.

Automatic evaluation transitions should be traceable through:

- alert timestamps and metadata;
- evaluation run;
- optional occurrence model.

No duplicate audit event should be created for unchanged daily evaluation. Audit is for meaningful transitions and user actions, not every no-op run.

## 29. Notification Boundary

Alert evaluation:

- determines and persists current alert state.

Notification selection:

- chooses which alerts should be sent.

Delivery:

- sends e-mail.

Future task: `FIN-ALERT-003` Weekly Alert Email Digest.

Weekly digest must:

- send only applicable open/acknowledged alerts;
- group by recipient and Project;
- avoid resending unchanged alerts too frequently;
- store delivery history;
- use project-related people/roles;
- support safe opt-out/preferences.

No e-mail code belongs in initial detection implementation.

## 30. Recipient Resolution For Future E-Mail

Future recipient sources:

- Project manager;
- accounting contact;
- management;
- explicitly subscribed ProjectParty;
- organization financial admins.

Do not send to every ProjectParty by default. Financial alert e-mails can contain sensitive values and must resolve recipients through explicit role/policy and future notification preferences.

Future notification preference model should support:

- user or party identity;
- alert type subscription;
- severity threshold;
- digest frequency;
- opt-out;
- Project-specific subscription;
- delivery channel.

## 31. Privacy And Safety

Alerts may contain sensitive financial information.

Rules:

- enforce organization isolation;
- require role-based access;
- authorize e-mail recipients before delivery;
- keep user-facing messages safe;
- do not expose secrets, raw GL payloads, raw API responses, or unrelated Project data;
- financial values must not leak across Projects or organizations;
- future delivery must be audited.

Central alert views should be treated as management/finance surfaces, not general project notes.

## 32. Performance

Evaluation must avoid:

- one uncontrolled query tree per Project;
- loading raw GL payloads;
- evaluating Projects with no eligibility;
- recalculating lifetime periods repeatedly without bounds.

Future optimizations:

- candidate queries per rule type;
- batch aggregation;
- cached financial snapshots;
- incremental evaluation only for Projects affected by changed GL periods;
- Project activity index;
- per-organization evaluation window.

Do not introduce financial snapshots in this architecture task.

## 33. Initial Management Command

Future command:

```powershell
python manage.py evaluate_financial_alerts
```

Options:

- `--organization ID`
- `--date YYYY-MM-DD`
- `--project ID` repeatable
- `--alert-type`
- `--dry-run`
- `--debug`

The command should call the service layer, print safe summaries, support dry-run, and never call Merit or e-mail delivery directly.

## 34. Testing Strategy

Future model tests:

- constraints;
- fingerprint uniqueness;
- lifecycle timestamps;
- organization isolation.

Future detection tests:

- lifetime negative;
- current-month negative;
- no revenue;
- management vs accounting basis;
- currency;
- data quality;
- current-month boundaries;
- lifetime period;
- deduplication;
- reopen;
- resolve;
- acknowledge/dismiss;
- dry run;
- no API calls;
- no source mutation.

Future UI tests:

- filters;
- sorting;
- Project panel;
- actions;
- safe output;
- permissions.

Notification tests belong to the later digest/delivery implementation.

## 35. Migration Strategy

Implementation sequence:

1. `FIN-ALERT-001` Alert Models and Detection Engine.
2. `MVP-FIN-004` Financial Alerts List and Project UI.
3. `FIN-ALERT-002` Scheduled Evaluation.
4. `FIN-ALERT-003` Weekly Alert Email Digest.

The first migration should preserve extensibility without overbuilding:

- add core lifecycle records and deterministic fingerprints;
- add minimal policies required for initial alert types;
- keep notification delivery out;
- keep invoice-issued alert out until sales-invoice cache exists.

## 36. Architecture Decisions

Decisions recorded by this architecture:

- alerts are persisted lifecycle records;
- financial facts come from existing financial services;
- fact and policy are separated;
- detection and delivery are separate;
- current no-revenue alert is not an invoice-issued assertion;
- alerts are never hard-deleted;
- accounting and management values remain both traceable.

See `DECISIONS.md` for the ADR.

## 37. README

`README.md` should reference this document and describe planned central financial alerts, Project-level alert visibility, and later weekly e-mail digest delivery.

## 38. ROADMAP

Roadmap alignment:

- Current architecture phase: Financial Alert Architecture.
- Planned implementation: `FIN-ALERT-001` Alert Models and Detection Engine.
- Planned UI: `MVP-FIN-004` Financial Alerts List and Project UI.
- Planned scheduling: `FIN-ALERT-002` Scheduled Evaluation.
- Planned notification: `FIN-ALERT-003` Weekly Alert Email Digest.

## 39. FEATURE_INDEX

If `FEATURE_INDEX.md` exists, it should record:

- Financial Alert Architecture: completed.
- Alert Models and Detection Engine: planned.
- Financial Alerts List and Project UI: planned.
- Scheduled Evaluation: planned.
- Weekly Alert Email Digest: planned.

Do not create `FEATURE_INDEX.md` only for this task.

## 40. Non-Goals

Do not implement in this task:

- models;
- migrations;
- detection services;
- commands;
- UI;
- scheduled jobs;
- e-mail sending;
- invoice import;
- alert AI;
- SMS/Slack notifications;
- budgets/forecasts;
- automatic financial correction;
- Merit write-back.

## Architecture Review Checklist

- Financial formulas are not duplicated.
- Alert facts and policies are separate.
- Accounting and management bases are explicit.
- Current-month and lifetime semantics are precise.
- No-revenue wording does not overclaim invoice status.
- Fingerprints prevent duplicates.
- Lifecycle supports acknowledge, resolve, dismiss, and reopen.
- Alerts are persisted and auditable.
- Detection is independent of notification delivery.
- Central and Project-level UI boundaries are defined.
- Weekly digest is deferred to phase 2.
- Organization isolation and financial privacy are explicit.
