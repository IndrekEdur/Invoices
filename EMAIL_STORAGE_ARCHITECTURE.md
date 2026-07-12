# Intelligent Email Storage Architecture

This document defines how the Operations Workspace Platform should safely index, store, process, and retain very large mailboxes without downloading, duplicating, or processing all attachments at once.

It follows `PLATFORM_ARCHITECTURE.md`, `COMMUNICATION_ARCHITECTURE.md`, `EMAIL_PROCESSING_EPIC.md`, `KNOWLEDGE_ARCHITECTURE.md`, `PROJECT_ARCHITECTURE.md`, `SETTINGS_ARCHITECTURE.md`, and `ENGINEERING_GUIDE.md`.

## 1. Vision

The Workspace is not a mirror of the IMAP server.

It is an operational memory and searchable business index. E-mail import should preserve business history, context, evidence, questions, attachments, project links, decisions, and future documents even when the original mailbox changes.

Imported e-mails must remain available when:

- the message is deleted from the mail server;
- the mailbox is reorganized;
- an IMAP folder is renamed;
- the original account is disconnected.

Deleting a remote e-mail must not automatically delete the Workspace record. Remote mailbox state is provider state. Workspace records are organization memory and must be governed by explicit retention, permission, and audit policies.

## 2. Main Risks

A first production mailbox may contain roughly 50 GB of data, much of it in attachments. A naive full import would create technical and business risk.

Main risks:

- long-running synchronous web requests;
- excessive RAM use from loading full messages or attachments at once;
- SQLite and relational database growth from storing binaries in rows;
- duplicate messages from repeated syncs or folder copies;
- duplicate attachments across threads and forwarded messages;
- repeated full-mailbox scans;
- IMAP timeouts and provider throttling;
- partial imports that cannot be resumed;
- failed retries that create duplicates;
- attachment malware or unsafe file types;
- oversized attachments;
- HTML and inline-image bloat;
- user interface slowdown from huge querysets;
- accidental propagation of remote deletion into Workspace history.

The architecture must make import incremental, idempotent, resumable, observable, and conservative with binary downloads.

## 3. Storage Layers

E-mail storage is split into separate layers. These layers should not be collapsed into one table or one file mirror.

### A. Message Index

The message index stores searchable communication data:

- provider and account identity;
- external message id;
- internet `Message-ID`;
- external thread id;
- IMAP UID;
- UIDVALIDITY;
- mailbox/folder identity;
- subject;
- sender and recipients;
- sent and received timestamps;
- normalized body text;
- optional sanitized HTML;
- direction;
- processing state;
- remote presence state;
- metadata.

Existing capability: `EmailAccount`, `EmailThread`, `EmailMessage`, `RawEmailMessage`, `IMAPEmailConnector`, `EmailSyncService`, and `EmailImportService` already provide the first version of this layer. They should be extended rather than recreated.

### B. Attachment Manifest

The attachment manifest stores metadata about attachments without requiring immediate binary download:

- e-mail message;
- original filename;
- MIME type;
- reported size;
- content id;
- disposition;
- provider attachment locator;
- checksum if downloaded;
- download status;
- storage status;
- optional `Document` link;
- metadata.

Existing capability: `EmailAttachment` already preserves the communication-origin object and can link to `Document`. It should grow into the attachment manifest instead of being replaced.

### C. Binary Object Storage

Actual file bytes should live outside normal relational database rows.

Future storage options:

- local filesystem for development;
- Dropbox integration;
- S3-compatible object storage;
- Azure Blob Storage;
- other providers through a storage adapter.

Relational rows should store stable object references, checksums, sizes, MIME types, and metadata, not large binary payloads.

### D. Business Documents

Only attachments entering business workflows become `Document` objects through `DocumentStorageService`.

Do not make every e-mail attachment automatically a `Document`. An inline logo, signature image, or irrelevant brochure may remain an attachment occurrence only. Invoices, contracts, drawings, specifications, and other business-relevant files can be converted to `Document` when policy or the user requests it.

Existing capability: `Document`, `DocumentVersion`, `DocumentStorageService`, and `EmailAttachmentDocumentService` already define this boundary and must be reused.

## 4. Import Strategy

Import should be staged.

### Stage 1: Discovery And Essential Metadata

- Fetch headers and essential message metadata.
- Persist or update `EmailMessage`.
- Avoid attachment binary downloads.
- Record attachment manifest metadata when provider data makes it available.
- Store provider cursor state.

### Stage 2: Body Fetch And Lightweight Processing

- Fetch and normalize body text in controlled batches.
- Store sanitized HTML only when useful.
- Run project suggestion and question detection after message persistence.
- Keep processing retryable and separate from message import.

### Stage 3: Selected Attachment Download

- Download selected attachment bytes on demand or by policy.
- Calculate checksum.
- Store bytes through a binary storage adapter.
- Optionally convert attachment to `Document` through `DocumentStorageService`.

Initial production import should support:

- newest-first processing;
- configurable date window;
- configurable batch size;
- continuation cursor;
- resumability;
- pause and resume;
- progress reporting;
- retry without duplication.

## 5. Incremental Synchronization

Normal sync must not scan and fetch the full mailbox every time.

Provider cursors and identifiers should be preferred:

- IMAP UID;
- UIDVALIDITY;
- mailbox/folder identity;
- last successfully processed UID;
- provider delta tokens for future Microsoft 365/Gmail;
- received date only as fallback.

UIDVALIDITY changes mean the server may have reassigned UIDs. Safe recovery behavior:

- mark the mailbox cursor as invalidated;
- avoid deleting Workspace messages;
- re-discover headers for the affected mailbox;
- match existing messages by internet `Message-ID` and fingerprint before creating new rows;
- record audit/progress events explaining the recovery.

## 6. Idempotency And Duplicate Prevention

The same message fetched repeatedly must update or return the existing `EmailMessage`, not create duplicates.

Identity hierarchy:

1. account + external message id / IMAP UID where stable;
2. internet `Message-ID`;
3. fallback fingerprint if provider ids are unavailable.

Fallback message fingerprint inputs may include:

- normalized sender;
- sent timestamp;
- normalized subject;
- body hash;
- attachment manifest summary.

Existing capability: `EmailImportService.import_message(...)` already uses account + external message id with update-or-create semantics. Future import should extend that idempotency to mailbox UID state, internet `Message-ID`, and fallback fingerprints.

## 7. Attachment Deduplication

Attachment bytes should use content-addressed identity once downloaded.

The stable binary identity is SHA-256 over the downloaded bytes. The same binary content appearing in multiple e-mails should be stored once where the storage backend supports it.

Keep these identities separate:

- `EmailAttachment` occurrence: this exact message had this attachment.
- Stored binary object: bytes stored once by checksum and backend key.
- `Document`: business-file identity with status, workflow, versions, and business meaning.

One stored binary may be referenced by:

- multiple `EmailAttachment` records;
- one or more business `Document` records where policy allows.

Do not merge business `Document` records automatically merely because bytes match. The same PDF attached to two different projects may require separate business context.

## 8. Lazy Attachment Download

Default historical import behavior:

- index attachment metadata;
- do not download the binary immediately;
- download only when there is a reason.

Download triggers:

- user opens the attachment;
- user converts it to `Document`;
- policy marks it important;
- OCR or extraction requires it;
- project workflow requests it.

Architectural attachment states:

- `metadata_only`;
- `queued`;
- `downloading`;
- `downloaded`;
- `failed`;
- `quarantined`;
- `unavailable_remote`;
- `stored`;
- `converted_to_document`.

These are architectural concepts only in this task. Model fields should be added later through focused implementation stories.

## 9. Remote Deletion And Retention

Remote deletion must not delete Workspace data.

Future remote state may track:

- `present`;
- `missing`;
- `deleted`;
- `moved`;
- `unknown`;
- `remote_deleted_at`;
- `last_verified_at`.

Workspace deletion must be explicit, permission-controlled, and audited. Remote mailbox sync should update remote presence state, not erase business memory.

Retention policy must be defined separately for:

- message metadata;
- normalized message body;
- sanitized HTML;
- attachment manifest;
- downloaded binary cache;
- `Document`;
- `DocumentVersion`;
- audit records.

Business `Document` and audit records require stronger retention than temporary attachment binary cache.

## 10. Body Storage

E-mail bodies need careful handling.

Body types and risks:

- plain text may include long quoted threads;
- HTML may contain tracking pixels, unsafe markup, and inline images;
- quoted replies can create repeated storage and noisy AI context;
- signatures create repeated low-value text;
- very large bodies can slow search and rendering;
- malformed encodings can fail parsers.

Recommended approach:

- preserve original source metadata where needed;
- store normalized body text for search and AI;
- sanitize HTML before display;
- avoid embedding large inline binaries in database fields;
- extract or collapse quoted replies where useful;
- keep parsing failures isolated to the message, not the batch.

## 11. Processing Pipeline

Target flow:

```text
IMAP Connector
-> Message Discovery
-> Raw Message DTO
-> Email Import
-> Attachment Manifest
-> Email Processing
-> Project Suggestion
-> Question Detection
-> Knowledge
-> Optional Attachment Download
-> Optional Document Conversion
```

Processing must remain independently retryable.

Failures in these steps must not require re-importing the e-mail itself:

- question detection;
- project suggestion;
- attachment download;
- document conversion.

Boundary preservation:

- Connector reads provider data.
- Import service persists communication objects.
- DocumentStorageService owns business-document storage.
- EmailAttachment remains the communication-origin object.
- Document remains the business-file identity.
- Knowledge builders read existing objects.
- Workspace UI does not own storage logic.

## 12. Batch And Background Execution

Future job types:

- mailbox discovery job;
- message metadata import job;
- body fetch job;
- attachment manifest job;
- attachment download job;
- e-mail processing job;
- retry/dead-letter job;
- historical backfill job.

A future background worker architecture should be introduced before full historical imports. Celery or another queue can be considered later, but this document does not select or implement a permanent worker technology.

Rules:

- do not hold web requests open during long network operations;
- do not keep one database transaction open during a long mailbox scan;
- persist progress per batch;
- expose import status to users.

## 13. Transaction Boundaries

Network fetch and local persistence have different failure modes.

Transaction rules:

- network fetch should not run inside one large database transaction;
- persist progress per message or batch;
- one bad message should not roll back the full mailbox import;
- local persistence for each message should remain transactional;
- external storage writes and database writes require retry or compensating logic;
- audit important state changes and external actions.

Existing note: `EmailSyncService` already keeps connector fetch outside its audit transaction. Future batch imports should continue that direction and make progress persistence more granular.

## 14. Capacity Planning

Storage categories:

- relational metadata;
- normalized message bodies;
- optional raw MIME source if retained;
- attachment binaries;
- document versions;
- search indexes;
- audit data;
- future knowledge snapshots.

The design must support:

- tens or hundreds of thousands of e-mails;
- mailbox sizes above 50 GB;
- gradual migration from SQLite development storage to production-grade PostgreSQL;
- external binary storage.

SQLite remains suitable for development and small pilot use, but a large production mailbox should move to PostgreSQL and external binary storage before full historical import.

## 15. Search And Knowledge

The searchable index should include:

- subject;
- sender and recipients;
- body text;
- project;
- question status;
- attachment filename;
- document text in future.

Knowledge Engine should consume verified and processed context, not raw binary attachments by default.

Large binary storage must not be passed directly to AI. AI should receive controlled context from Knowledge Builders or future AI Context Providers: normalized text, metadata, evidence, extracted document text, and source references.

## 16. Security

Security requirements:

- secret isolation through provider abstractions;
- TLS for mailbox and storage connections;
- attachment size limits;
- MIME validation;
- malware scanning in a future capability;
- filename normalization;
- path traversal prevention;
- HTML sanitization before display;
- access permissions;
- organization isolation;
- secure temporary files;
- no secret or raw credential logging;
- audit of attachment downloads and `Document` conversion.

Attachment download must be treated as a potentially risky external input operation, not a harmless file copy.

## 17. Observability And Health

Future sync status should expose:

- mailbox;
- phase;
- started_at;
- last_progress_at;
- discovered count;
- imported count;
- skipped duplicate count;
- failed count;
- attachments indexed;
- bytes downloaded;
- cursor;
- current state;
- last safe error;
- retry count.

Users should see:

- last successful sync;
- initial import progress;
- partial failure warnings;
- storage usage;
- failed attachment downloads.

Operational visibility is part of product trust. A 50 GB mailbox import must feel observable, not frozen.

## 18. User Controls

Settings should later provide:

- initial import date range;
- batch size;
- newest-first or oldest-first;
- fetch bodies toggle;
- attachment policy:
  - metadata only;
  - below size threshold;
  - selected MIME types;
  - on demand;
  - all;
- maximum attachment size;
- pause/resume import;
- storage backend;
- retention policy.

Safe defaults:

- metadata/body import in limited batches;
- attachment metadata only;
- no automatic full 50 GB binary download.

## 19. Dropbox And Storage Integration

Future relationship:

```text
EmailAttachment
-> Binary Storage Adapter
-> Dropbox or object storage
-> optional DocumentStorageService conversion
```

Dropbox folder organization must not become the primary relational identity.

Provider paths may change. Internal ids, provider object ids, and checksums remain stable. Dropbox behavior must not be hardcoded into Communication or Document models. Storage providers should be reached through adapters/services.

## 20. MVP Implementation Path

Future tasks:

- `EMAIL-STORAGE-001` Sync Cursor and Mailbox State
- `EMAIL-STORAGE-002` Batch Historical Import Service
- `EMAIL-STORAGE-003` Attachment Manifest DTO and Parsing
- `EMAIL-STORAGE-004` Lazy Attachment Download Service
- `EMAIL-STORAGE-005` Binary Object Storage Abstraction
- `EMAIL-STORAGE-006` Attachment Checksum and Deduplication
- `EMAIL-STORAGE-007` Remote Deletion Tracking
- `EMAIL-STORAGE-008` Import Progress and Health UI
- `EMAIL-STORAGE-009` Historical Import Settings UI
- `EMAIL-STORAGE-010` PostgreSQL Production Migration Plan
- `DROPBOX-000` Dropbox Integration Architecture

## 21. Non-goals

Do not implement now:

- downloading all historical attachments;
- copying the entire mailbox as raw MIME;
- remote deletion propagation;
- automatic permanent deletion;
- Dropbox integration;
- object storage;
- background workers;
- OCR;
- malware scanning;
- vector indexing;
- AI-based retention decisions;
- full historical import.

## 22. Engineering Rules

Rules:

- Never load the whole mailbox into memory.
- Never import the whole mailbox in one transaction.
- Sync must be idempotent and resumable.
- Remote deletion must not delete business history.
- Attachment occurrence, binary object, and `Document` are separate identities.
- Large binaries do not belong in relational database fields.
- Connectors discover/fetch; services persist and decide.
- Document conversion uses `DocumentStorageService`.
- Every external or destructive action is auditable.
- Historical import must be controllable and observable.

These rules are extensions of the existing service-layer and integration-boundary rules in `ENGINEERING_GUIDE.md`.
