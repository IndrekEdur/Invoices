# Platform Settings Architecture

## 1. Vision

Settings is the operational control center of the platform.

It is not a technical admin panel and it is not a replacement for Django Admin. It is the Workspace area where authorized users configure how the platform behaves for their Organization: integrations, users, operational rules, sync status, credentials, security controls, knowledge behavior, and future automation settings.

Normal setup must not require Django shell, PowerShell scripts, direct database edits, or developer-only tools. An administrator should be able to open the Workspace, configure an e-mail account, test the connection, configure Merit, sync project dimensions, review health, and understand what is safe to activate.

Settings must make operational configuration visible, auditable, and safe.

## 2. Principles

- No shell is required for normal setup.
- Secrets are never exposed after save.
- Settings are Organization-scoped by default.
- Access is role-based.
- Workspace views call service-layer APIs only.
- Every sensitive change creates an AuditEvent.
- External connections can be tested before activation.
- External writes require explicit user approval.
- Defaults must be conservative and safe.
- Configuration errors should be explainable in plain language.
- Settings must separate connection configuration from business workflow decisions.

## 3. Settings Areas

### General

General settings describe the Organization's default operating context: language, timezone, currency, date format, number format, default dashboard behavior, and workspace preferences.

### Organization

Organization settings manage the top-level tenant identity:

- name
- legal name
- registration number
- VAT number
- country
- default currency
- timezone
- active status

Accounting modules, integrations, projects, documents, workflow, knowledge, and audit records operate inside an Organization.

### Users & Roles

Users & Roles settings manage who can access the platform and what they may do. The MVP can start with simple roles, but the architecture must support future granular permissions.

Typical permissions include:

- view projects
- manage projects
- review e-mail project links
- manage integrations
- update secrets
- sync accounting data
- create external accounting records
- approve AI drafts
- manage users
- view audit logs

### Email Accounts

Email Account settings manage inbound mailbox connections and future provider-specific options.

Supported provider concepts include:

- IMAP
- Microsoft 365
- PST import
- Gmail
- other

### Accounting Integrations

Accounting Integration settings manage accounting providers such as Merit, future Standard Books, Xero, Exact, and other systems.

These settings configure connection metadata and integration health, while business actions remain explicit service-layer workflows.

### Merit

Merit settings are the first concrete accounting integration settings area. Merit remains an external accounting system; Workspace manages operational context and syncs through explicit, auditable integration services.

### Project Numbering

Project Numbering settings define how Workspace suggests project codes and how those codes align with accounting dimension values.

### Sync & Jobs

Sync & Jobs settings show manual and future scheduled synchronization status for e-mail, Merit dimensions, documents, background jobs, and other integrations.

### Documents

Document settings define storage behavior, allowed file types, upload limits, retention rules, OCR defaults, and future document classification options.

### Knowledge

Knowledge settings define how organizational memory is built, retained, searched, and exposed to AI context providers.

### AI Assistant

AI Assistant settings define safe defaults for summarization, draft generation, prompt templates, review requirements, model/provider choices, and future usage limits.

AI settings must never allow silent high-risk business changes.

### Dropbox / File Storage

Dropbox and File Storage settings will manage future file storage providers, project folder mapping, permissions, storage health, and sync status.

### Security

Security settings cover authentication, sessions, password policy, MFA future support, organization isolation, role assignment, secret access, and sensitive action confirmation.

### Audit

Audit settings expose important AuditEvents to authorized users and provide filters for sensitive changes, sync runs, external writes, role changes, and automation settings.

### System Health

System Health settings show whether the platform can safely operate:

- database status
- storage status
- e-mail sync status
- Merit API health
- last successful sync
- last error
- future queue/background job status
- future OCR/AI provider health

## 4. Email Account Settings

The Email Account settings UI should allow authorized users to create, edit, test, activate, and deactivate mailbox connections.

Fields:

- provider
- display name
- e-mail address
- username
- host
- port
- SSL/TLS flags
- secret/password
- active status
- metadata for provider-specific future options

Operational actions:

- test connection
- sync now
- view last sync time
- view last sync result
- view safe sync error message

Rules:

- Passwords and tokens are accepted through a secure form field but never displayed after save.
- Stored secrets are shown only as masked values.
- Sync actions call EmailSyncService.
- Provider-specific connection logic remains inside connectors.
- Workspace views do not contain IMAP or Microsoft 365 protocol logic.
- Connection test must not import messages unless the user explicitly chooses sync.

## 5. Accounting Integration Settings

Accounting Integration settings manage provider configuration and health.

Fields:

- provider
- display name
- API base URL
- API ID
- secret
- active status
- last sync time
- metadata

Operational actions:

- test connection
- sync dimensions
- view sync conflicts
- view last sync status
- deactivate integration

Rules:

- Accounting services and connectors own API behavior.
- Settings views never call external APIs directly.
- Secrets are accessed through SecretProvider.
- External writes require user confirmation.
- Sync conflicts are shown and reviewed; they are not silently resolved.

## 6. Merit Settings

Merit settings specialize Accounting Integration settings for Merit Aktiva.

Fields:

- Merit company/account label
- API ID
- API secret
- API base URL
- project dimension id
- project dimension name
- active status
- last dimension sync
- metadata for future Merit-specific configuration

Operational actions:

- test Merit connection
- sync Merit dimensions
- view dimension sync conflicts
- create missing Merit dimension value when user creates a Workspace project
- review code/name conflicts

Project dimension rules:

- Workspace Project.code should correspond to Merit project dimension value code.
- Merit `project_dimension_id` must be configured before Workspace can create Merit project dimension values.
- Creating a Merit dimension value is an external write and must be explicit.
- If Merit is unavailable, Workspace project creation may succeed while Merit dimension creation can be retried later.

## 7. Project Numbering Settings

Project Numbering settings define how new project codes are suggested.

Configuration concepts:

- numeric project codes
- prefix support
- minimum starting code
- next available code
- collision detection
- active/inactive project code handling
- awareness of cached Merit dimensions

Rules:

- Suggested codes use Workspace Projects and cached AccountingDimensions.
- Non-numeric codes can exist but are ignored for numeric allocation unless future rules define otherwise.
- Existing cached Merit project dimensions must be considered to prevent duplicates.
- The user confirms the suggested code before project creation.
- Future policies may allow automatic allocation under safe conditions, but external writes remain explicit unless approved by policy.

## 8. Secret Handling

Secrets are sensitive operational configuration and must be handled through a single abstraction.

Rules:

- Secrets are never displayed after save.
- UI shows masked values only.
- Secrets are never written into logs.
- Secrets are never included in audit metadata.
- Business services do not read raw secret fields directly.
- SecretProvider is the current abstraction.
- Future implementation should replace placeholder storage with encryption or a vault backend.
- Error messages must not include secret values.

Examples:

- Email password
- Merit API secret
- Future Microsoft 365 client secret
- Future Dropbox token
- Future AI provider API key

## 9. Permissions

Only authorized users can manage sensitive settings.

Permission areas:

- integrations
- secrets
- users
- roles
- accounting settings
- e-mail accounts
- AI settings
- external write actions
- audit visibility
- system health visibility

Sensitive actions should require either a dedicated permission or an elevated role.

Examples:

- A project manager may confirm project links but not edit Merit secrets.
- An accounting user may sync Merit dimensions but may not manage all user roles.
- An administrator may configure integrations and users.
- External write actions such as creating Merit dimension values require explicit confirmation.

## 10. Audit

Every sensitive settings action must create an AuditEvent.

Examples:

- integration created
- integration activated/deactivated
- secret updated
- e-mail account created or changed
- test connection executed
- sync run started/completed/failed
- Merit dimension created
- project numbering setting changed
- user invited
- user role changed
- AI automation setting changed
- storage provider setting changed

Audit payloads should include:

- Organization
- actor
- event type
- object type
- object id
- safe message
- non-secret metadata
- timestamp

AuditEvent is for compliance and traceability. It is not the DomainEvent store and it is not WorkflowEvent history.

## 11. System Health

System Health settings show whether the platform is operational.

Health sections:

- e-mail sync health
- Merit API health
- last successful e-mail sync
- last successful dimension sync
- last sync error
- database health
- storage health
- future queue/background job status
- future AI/OCR provider status

Health checks should distinguish:

- configured
- active
- test successful
- last sync successful
- currently failing
- permission missing
- secret missing
- external service unavailable

The UI should show safe error messages and recommended next actions.

## 12. MVP Settings Path

Implementation sequence:

1. SETTINGS-001 Settings Workspace
2. SETTINGS-002 Email Account Management UI
3. SETTINGS-003 Email Connection Test
4. SETTINGS-004 Accounting Integration Management UI
5. SETTINGS-005 Merit Connection Test
6. SETTINGS-006 Merit Dimension Sync Settings
7. SETTINGS-007 Project Numbering Settings
8. SETTINGS-008 Users and Roles Settings
9. SETTINGS-009 System Health Page

This sequence moves configuration from shell commands and database setup into the Workspace UI while keeping service-layer boundaries intact.

## 13. Non-goals

Do not implement immediately:

- full IAM system
- enterprise SSO
- full secret vault
- scheduled background jobs
- multi-company billing admin
- advanced policy editor
- complete audit search product
- all provider-specific settings

The first goal is safe, usable operational configuration for the current Workspace MVP.

## 14. Relationship to Other Documents

This document should be read together with:

- `PLATFORM_ARCHITECTURE.md`
- `UI_ARCHITECTURE.md`
- `MERIT_INTEGRATION_ARCHITECTURE.md`
- `COMMUNICATION_ARCHITECTURE.md`
- `MVP_ROADMAP.md`
- `ENGINEERING_GUIDE.md`

Settings is the Workspace-facing configuration layer for those architecture areas. It does not replace service-layer rules, connector boundaries, policy decisions, workflow history, or audit requirements.
