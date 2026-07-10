# Merit Verification Guide

This guide describes the safe manual workflow for verifying the real Merit Aktiva integration.

Do not commit real API keys. Do not paste secrets into tests, fixtures, screenshots, commits, issue text, or logs.

## 1. Create Accounting Integration

Open the Workspace:

```text
/workspace/settings/accounting-integrations/create/
```

Create an integration with:

- `provider`: `merit`
- `api_base_url`: Merit API base URL, for example `https://aktiva.merit.ee`
- `api_id`: Merit API ID
- `secret`: Merit API key
- `project_dimension_id`: Merit project dimension id used for project dimension values
- `is_active`: enabled

After saving, reopen the detail page and verify that the secret is shown only as a masked value.

## 2. Test Connection

On the accounting integration detail page, click `Test Connection`.

Expected result:

- success message says that Merit connection/configuration check succeeded
- provider is shown
- mode is shown when returned by health check
- response time is shown when available
- API secret is not displayed

If this fails, check:

- API ID is present
- secret was entered during create/edit
- provider is `merit`
- base URL is valid

## 3. Sync Dimensions

On the accounting integration list or detail page, click `Sync Merit Dimensions`.

Expected result:

- success or warning message shows created, updated, unchanged, archived, and conflict counts
- no raw API secret appears in UI or terminal output

## 4. Verify AccountingDimension Cache

Open Django admin or use Django shell/read-only inspection to confirm that `AccountingDimension` rows exist.

Check:

- `organization` is correct
- `provider` is `merit`
- `dimension_type` is `project`
- `code` matches Merit project dimension value code
- `name` matches Merit dimension value name
- `last_synced_at` is set

## 5. Project Code Allocation

Open:

```text
/workspace/projects/create/
```

Verify that suggested project code considers:

- existing Workspace projects
- cached Merit project dimensions

The suggested next code should not duplicate existing project dimension codes.

## 6. Create Project With Merit Dimension Value

On the create project page:

1. Enter project name and other project fields.
2. Enable `Create matching Merit dimension value`.
3. Submit the form.

Expected result:

- Workspace project is created
- Merit dimension value is created
- local `AccountingDimension` cache is updated by the accounting service
- user sees a success message

If Merit creation fails after the Workspace project is created, the Workspace project remains and the user can retry the Merit dimension step later.

## 7. Management Command Verification

Health/auth check only:

```powershell
python manage.py verify_merit_integration <integration_id>
```

Health/auth check plus dimension sync:

```powershell
python manage.py verify_merit_integration <integration_id> --sync-dimensions
```

Debug mode:

```powershell
python manage.py verify_merit_integration <integration_id> --sync-dimensions --debug
```

Debug mode may show exception class and message, but must still never show API secrets.

## 8. Common Errors

`Integration not found`

The provided integration id does not exist.

`Connection test failed`

Check provider, API base URL, API ID, and secret.

`Merit API credentials are not configured`

API ID or secret is missing.

`HTTP 401/403`

API ID, key, timestamp, or signature is invalid.

`HTTP 429`

Merit rate limit was reached. Wait and retry.

`Conflict count is greater than zero`

Dimension sync detected duplicate or inconsistent project codes. Review conflicts before creating new project codes.

## Safety Rules

- Never commit credentials.
- Never print raw secrets.
- Never paste secrets into tests.
- Never run real Merit calls from automated tests.
- Use `Test Connection` before sync.
- Use `--sync-dimensions` only when you intentionally want to update the local dimension cache.
