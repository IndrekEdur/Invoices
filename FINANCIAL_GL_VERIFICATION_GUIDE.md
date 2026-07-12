# Financial GL Verification Guide

This guide describes the safe operator-driven workflow for verifying real Merit general-ledger synchronization.

The verification workflow proves that real Merit data can be authenticated, fetched through the bounded GL sync pipeline, persisted into the local GL cache, repeated idempotently, and inspected for project allocation quality without exposing secrets.

## Prerequisites

- A configured `AccountingIntegration` with provider `merit`.
- Valid Merit API base URL, API ID, and API secret saved through Workspace Settings.
- The integration must be active before running a real sync.
- The GL sync implementation from `sync_general_ledger` must already be available.
- Use only a safe, closed or stable accounting period for first verification.

Do not commit credentials. Do not paste secrets into tickets, logs, screenshots, or chat.

## Identify The Integration ID

Preferred path:

1. Open Workspace Settings.
2. Go to Accounting Integrations.
3. Open the active Merit integration detail page.
4. Use the integration ID shown in the URL or page metadata.

Developer fallback:

```powershell
cd platform
python manage.py shell
```

```python
from apps.accounting.models import AccountingIntegration
AccountingIntegration.objects.filter(provider="merit").values("id", "display_name", "is_active")
```

Never print or inspect the stored secret value.

## Choose A Safe Period

Recommended first verification period:

- one completed calendar month;
- preferably closed or stable in accounting;
- explicit `--start` and `--end` dates supplied by the operator;
- no hardcoded month assumed by the system.

Example only:

```powershell
cd platform
python manage.py sync_general_ledger <integration_id> --start 2026-06-01 --end 2026-06-30
```

Replace dates with the period agreed for the real verification.

## Initial Read-Only Inspection

Before making a real API call, inspect the local cache:

```powershell
cd platform
python manage.py verify_general_ledger_sync <integration_id> --start YYYY-MM-DD --end YYYY-MM-DD
```

Without `--run-sync`, this command does not call Merit. It reads:

- `AccountingSyncState`;
- `AccountingSyncRun`;
- `AccountingGLBatch`;
- `AccountingGLEntry`;
- `AccountingGLAllocation`;
- linked `Project` and `AccountingDimension` rows.

## Run The First Real Sync

Run the existing sync pipeline and then local verification:

```powershell
cd platform
python manage.py verify_general_ledger_sync <integration_id> --start YYYY-MM-DD --end YYYY-MM-DD --run-sync
```

The verification command calls `GeneralLedgerSyncService`, which is the only GL sync orchestrator. It does not call `MeritAPIClient` directly.

## Repeat For Idempotency

Run the same period twice and check that existing source identities remain stable:

```powershell
cd platform
python manage.py verify_general_ledger_sync <integration_id> --start YYYY-MM-DD --end YYYY-MM-DD --run-sync --repeat-sync
```

Expected result:

- batch count unchanged after the second run;
- entry count unchanged;
- allocation count unchanged;
- stable source identities keep stable primary keys;
- second sync reports unchanged or updated rows rather than duplicate creates.

If Merit data changed between calls, updated rows may be legitimate. Treat the result as inconclusive rather than failed solely because `updated_count` is non-zero.

## Inspect Project Links And Unlinked Allocations

Project-linked samples are shown by default.

To also show unlinked allocation samples:

```powershell
python manage.py verify_general_ledger_sync <integration_id> --start YYYY-MM-DD --end YYYY-MM-DD --show-unlinked --sample-size 20
```

Unlinked allocations are data-quality findings. They are not automatically errors and must not create missing `Project` or `AccountingDimension` rows.

Common reasons:

- no exact `Project.code` match;
- no `AccountingDimension` match;
- blank dimension code;
- organization mismatch.

## Compare Totals With Merit

The command prints diagnostic source totals only:

- total debit amount;
- total credit amount;
- debit minus credit difference;
- total allocation amount;
- sum of batch total amounts where present;
- currencies represented;
- account codes represented;
- distinct project/dimension codes.

These totals are not revenue, cost, profit, or project result. Financial aggregation and account classification are later features.

When comparing with Merit, check:

- GL batch or document count where available;
- total debit and credit;
- selected account totals;
- selected transaction values;
- selected project/dimension allocations;
- changed or reversed transactions.

Do not rely on exact Merit UI menu names unless they have been verified separately.

If multiple currencies are present, totals are not directly comparable without currency normalization.

## Troubleshooting

Authentication failure:

- verify API ID and secret in Workspace Settings;
- run the Merit connection test;
- ensure no old or copied secret was saved accidentally.

No data:

- confirm the selected period has posted GL data in Merit;
- confirm the period uses document/posting dates, not changed dates;
- verify that the integration ID points to the correct Merit company.

Unlinked allocations:

- sync Merit dimensions;
- verify that `AccountingDimension.code` matches Workspace `Project.code`;
- confirm that project codes are stored consistently.

Non-zero debit/credit difference:

- treat as a warning unless the selected source response is known to be a fully balanced period;
- compare the same date basis in Merit;
- check whether partial, reversed, changed, or filtered transactions are involved.

Command failure:

- rerun without `--debug` for safe user-facing output;
- use `--debug` only in a trusted local terminal;
- never copy secrets, signatures, auth query strings, or raw authentication headers.

## Safe Output Rules

The verification workflow must never print:

- API secret;
- request signature;
- authentication query;
- credential-bearing URL;
- raw authentication headers;
- complete raw payload by default;
- stored secret field.

## Verification Record Template

```text
Integration:
Period:
Run date:
Operator:

First sync:
- batches:
- entries:
- allocations:
- created:
- updated:
- unchanged:

Second sync:
- created:
- updated:
- unchanged:
- duplicate change:

Control totals:
- debit:
- credit:
- difference:

Allocation quality:
- linked:
- unlinked:
- blank codes:

Merit comparison:
- verified:
- differences:
- notes:

Decision:
- accepted
- accepted with warnings
- rejected for investigation
```

## Non-Goals

This workflow does not implement:

- revenue/cost classification;
- account mapping;
- project financial aggregation;
- invoice import;
- payment import;
- alerts;
- financial UI;
- report generation;
- scheduled sync;
- automatic correction;
- project creation from unlinked dimension codes.
