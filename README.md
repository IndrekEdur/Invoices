# Operations Workspace Platform

This repository is evolving from a local invoice automation prototype into an Operations Workspace Platform: one business workspace where communication, projects, documents, workflows, knowledge, accounting, integrations, and AI assistance come together.

## Architecture Documents

`PLATFORM_ARCHITECTURE.md` is the top-level architecture document for the Operations Workspace Platform and explains how all engines, workspace areas, knowledge, AI, and future capabilities fit together.

`MVP_ROADMAP.md` defines the first production-usable Operations Workspace MVP for replacing daily operational workflows.

`ENTERPRISE_DOMAIN_MAP.md` describes the business domain vision: what the organization should know, remember, communicate, and act on.

`COMMUNICATION_ARCHITECTURE.md` describes how business communication, especially e-mails, becomes part of organization memory.

`PROJECT_ARCHITECTURE.md` describes Project as the primary business context connecting people, documents, communication, workflows, accounting, and knowledge.

`EMAIL_PROCESSING_EPIC.md` describes the end-to-end lifecycle of an incoming business e-mail from arrival to accounting, learning, and business memory.

`EMAIL_STORAGE_ARCHITECTURE.md` describes how large mailboxes are imported as searchable message and attachment indexes with lazy attachment download, resumable sync, remote deletion protection, and future external binary storage.

The communications app includes persistent mailbox sync state so each EmailAccount mailbox can later track resumable cursor progress, UIDVALIDITY, import status, safe errors, and observable counters.

Normal IMAP sync now uses incremental UID-based mailbox cursors. It resumes from the last successfully processed UID, preserves bounded latest-message behavior for first/no-cursor syncs, and still leaves historical full-mailbox backfill for a later implementation.

`KNOWLEDGE_ARCHITECTURE.md` describes the Knowledge Engine as the controlled memory, evidence, timeline, and AI context layer of the platform.

`UI_ARCHITECTURE.md` describes the future platform user experience as a business workspace, not a Django Admin replacement.

`MERIT_INTEGRATION_ARCHITECTURE.md` describes how Workspace project codes synchronize with Merit Aktiva dimensions through explicit, auditable integration services.

`FINANCIAL_REPORTING_ARCHITECTURE.md` describes how Workspace will import Merit general-ledger transactions, invoices and payments into an auditable local cache for project financial reporting, reconciliation, alerts and controlled report distribution.

`MANAGEMENT_COST_ALLOCATION_ARCHITECTURE.md` describes the internal management accounting layer for allocating indirect costs to projects without modifying Merit or synchronized GL cache data.

`FINANCIAL_GL_VERIFICATION_GUIDE.md` describes the safe manual workflow for verifying real Merit GL synchronization, idempotency, local cache quality, diagnostic totals, and project allocation links.

`MERIT_VERIFICATION_GUIDE.md` describes the safe manual workflow for verifying real Merit credentials, connection checks, dimension sync, local cache updates, and project dimension creation.

`SETTINGS_ARCHITECTURE.md` describes how administrators manage organizations, users, roles, e-mail accounts, accounting integrations, Merit settings, secrets, sync health, and system configuration from the Workspace UI.

The accounting app includes a project code allocation service that suggests the next available numeric project code from existing Workspace projects and cached accounting dimensions.

The projects app includes a controlled project creation service that creates a Project with the suggested next available code and records an audit event.

The accounting app includes a reusable Merit API client connector for signed HTTP communication, health checks, JSON parsing, timeout handling, and sanitized exception mapping. Future Merit services should use this connector instead of performing direct HTTP calls.

Merit API authentication is isolated in `MeritAuthenticationService`, which creates official `apiId`, `timestamp`, and `signature` query authentication values without exposing API secrets.

The Merit API client exposes dimension read/create methods that return immutable DTOs without writing Workspace or accounting database records.

The Merit API client exposes a `create_dimension_value(...)` method for creating or updating Merit dimension values such as project codes through `senddimvalues`, while keeping database persistence in separate services.

The Merit API client exposes a bounded GL full-details read method for 31-day general-ledger batch downloads, returning typed DTOs without persistence or reporting calculations yet.

The accounting app includes persistent accounting sync cursor and run tracking so GL, sales invoices, purchase invoices, payments and other accounting sources can later be synced incrementally and observed independently.

The accounting app includes a normalized general-ledger cache for batches, entries and allocation lines. Merit connector DTOs and local persistence are separate; GL synchronization and financial reporting are still planned.

The accounting app includes a GL transaction synchronization service and `sync_general_ledger` management command for bounded 31-day Merit GL periods.

The accounting app includes exact-code account classification configuration and a read-only project financial aggregation service. Project totals are calculated from local GL allocation rows, unclassified amounts stay visible and excluded from trusted result totals, and no financial UI or alert rules exist yet.

The accounting app includes Management Cost Pool and Allocation Rule models for the future management accounting layer. Cost pools, GL account mappings, monthly periods, versioned allocation entries and rule configuration are stored separately from synchronized Merit GL cache data.

The accounting app includes a monthly management allocation proposal service. It generates draft allocation versions for explicitly selected Projects using revenue-proportional, equal, project-manager, manual percentage, or manual amount strategies. Source amounts come from mapped local GL accounts or an explicit manual amount, proposals remain draft for later review/approval, and no Merit write-back occurs.

The Workspace Management Allocations UI at `/workspace/management-allocations/` lets users generate, review, edit, approve and revise monthly management allocation drafts. Approved versions are immutable, revisions create new draft versions, only one approved version can exist for each pool/month, and Project Financials integration remains a later step.

GL Account Classification Settings at `/workspace/settings/account-classifications/` lets administrators map imported GL account codes into reporting categories without Django admin or shell commands. Mappings are exact-code, integration-scoped, audited, and affect project financial aggregation immediately without GL re-sync.

Project Financial Overview UI at `/workspace/projects/<id>/financials/` shows monthly and period-based revenue, cost, result, margin, data-quality warnings, unclassified account impact, sync status, and read-only allocation drill-downs from local synchronized GL allocations. Invoice/payment reporting, alerts, snapshots, and report distribution are not implemented yet.

Project Financial Overview includes a server-rendered vertical monthly revenue/cost/result chart. The chart uses already aggregated monthly values, keeps the numeric monthly table below it, and does not call Merit while rendering.

Project Financials now formats monetary values with consistent two-decimal display, includes labeled Y-axis gridlines on the monthly chart, and keeps the Workspace sidebar visible while long desktop pages scroll.

Organization Financial Dashboard at `/workspace/financials/` compares selected-month project revenue, cost, result, margin and data quality from local synchronized GL allocations. Its project comparison chart renders Revenue, Cost and Result bars on one shared monetary scale, while margin remains a separate percentage indicator. It ranks projects by highest revenue by default, keeps completed and archived projects visible when they have financial activity, and avoids silently combining mixed-currency totals.

The Financial Dashboard can manually synchronize one selected calendar month of Merit general ledger data through the existing `GeneralLedgerSyncService`. The sync is organization-wide, runs synchronously for the selected month, and leaves multi-month historical backfill, background execution, scheduled GL sync, and progress polling for later implementation.

Read-only project financial summary example:

```powershell
cd platform
python manage.py project_financial_summary <project_id> --start 2026-06-01 --end 2026-06-30 --currency EUR --show-unclassified
```

The accounting app includes a read-only `verify_general_ledger_sync` management command for operator-driven real Merit GL verification. Real API calls happen only when `--run-sync` is explicitly provided.

The accounting app includes an AccountingDimensionValueService that creates or updates Merit dimension values through the connector and updates the local AccountingDimension cache only after the API call succeeds.

The accounting app includes a Merit dimension sync engine that copies Merit dimension DTOs into the local AccountingDimension cache, records audit events, and reports conflicts without creating projects or resolving conflicts silently.

The accounting app includes a minimal SecretProvider abstraction so external API credentials can be centralized before real encrypted storage or vault integration is added.

The Workspace Projects UI at `/workspace/projects/` shows Workspace projects together with cached accounting project dimensions, project code status indicators, filters, search, detail placeholders, and a controlled create-project flow using suggested project codes.

The Workspace Projects UI supports safe project status management for active, completed and archived projects through audited service-layer actions. Status changes do not close or reopen Merit dimensions yet; that external accounting behavior is planned as a later explicit integration step.

The Workspace Projects UI can create an active Workspace Project directly from a cached Merit project dimension. Matching historical GL allocations with the same exact project code are linked immediately, so Project Financials becomes available without rerunning GL sync.

The Workspace Projects UI includes a CSRF-protected manual `Sync Merit dimensions` action that refreshes cached Merit project dimensions through the accounting sync service and reports created, updated, unchanged, archived and conflict counts.

The Dimension Conflict Review UI at `/workspace/accounting/dimensions/conflicts/` shows the latest Merit dimension sync conflicts from audit metadata for safe manual review without resolving, deleting, or writing to external APIs.

The accounting app includes a dimension conflict resolution service for explicit, audited local-cache decisions such as keeping local data, accepting incoming cache data, marking a local dimension inactive, or requiring manual review.

The Workspace Project Create UI can optionally create and cache a matching Merit project dimension value when an active Merit integration has a `project_dimension_id` configured.

The Settings Workspace at `/workspace/settings/` provides a read-only operational control center for summary counts, settings areas, e-mail accounts, accounting integrations, Merit configuration, project numbering and system health.

Email Account Management at `/workspace/settings/email-accounts/` lets administrators list, create, view and edit IMAP/email accounts while keeping stored secrets masked and out of rendered HTML.

Email account settings include a safe `Test Connection` POST action for IMAP accounts that checks connectivity and mailbox visibility without fetching or importing messages.

Accounting Integration Management at `/workspace/settings/accounting-integrations/` lets administrators list, create, view and edit Merit/accounting integrations while keeping stored API secrets masked and out of rendered HTML.

Accounting integration settings include a safe `Test Connection` POST action for Merit that calls the connector health check without syncing dimensions or exposing API secrets.

The Project Workspace at `/workspace/projects/<id>/` uses ProjectKnowledgeBuilder to show project overview, timeline, communications, documents, people, addresses, knowledge evidence, questions and audit history.

Project link review actions are available in the Inbox, e-mail detail and Reviews workspace so users can confirm, reject or correct e-mail to project suggestions through audited service-layer actions.

E-mail reply draft actions are available from the Inbox detail and Reviews workspace so users can create, mark for review, approve, or reject stored answer drafts before any future sending step exists.

## Testide käivitamine

Käivita testid repo juurkaustast:

```powershell
$env:PYTHONPATH = "."
python -m unittest discover -s tests
```

Codexi bundeldatud Pythoniga:

```powershell
$env:PYTHONPATH = "."
C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests
```

Uue Django platform skeletoni smoke-test:

```powershell
cd platform
python manage.py test apps.core
```

## Workspace UI

The first Operations Workspace UI skeleton is available under `/workspace/`.

It uses a Django Templates + HTMX-first approach. The current version provides reusable layout, navigation, placeholder pages, and HTMX-ready regions without business functionality yet.

The workspace design system demo is available under `/workspace/design-system/` and contains reusable server-rendered components for buttons, cards, badges, statuses, empty states, tables, headers, and form fields.

The dashboard MVP at `/workspace/dashboard/` is data-driven and reads existing e-mails, project suggestions, questions, answer drafts, projects, documents, workflow instances, and audit events.

The inbox MVP at `/workspace/inbox/` lists imported e-mails with project suggestions, question counts, attachment counts, filters, search, and a basic read-only detail page.

Workspace UX polish has been completed for the dashboard, inbox, shared layout, sidebar, badges, tables, empty states, and buttons.

Manual e-mail sync is available from the dashboard and inbox through a CSRF-protected `Sync now` POST action that uses the existing EmailSyncService.

Väike esimene prototüüp, mis loeb Outlooki `.pst` faili, leiab võimalikud arved ning salvestab kontrolltabeli CSV ja JSON formaadis.

## Rakenduste käivitamine

### Legacy lokaalne app

Olemasolev brauseriliides jääb põhirakenduseks seni, kuni Django platvorm on valmis:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_web_ui.ps1 -InputCsv ".\invoice_scan_output_outlook_refined\clean_invoice_candidates.csv" -DbPath ".\invoice_register.sqlite" -Port 8765
```

Seejärel ava:

```text
http://127.0.0.1:8765
```

### Uus Django platform skeleton

Django platvorm asub kaustas `platform/` ja on praegu tühi paralleelne karkass:

```powershell
pip install -r requirements.txt
cd platform
python manage.py runserver 127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/health/
```

## Mida see praegu teeb

- käib PST kaustad rekursiivselt läbi;
- loeb kirja pealkirja, saatja, kuupäeva, keha eelvaate ja manused;
- salvestab manused kuupõhistesse kaustadesse;
- proovib PDF-manustest teksti eelvaadet lugeda;
- annab igale kirjale arvekandidaadi skoori 0-100;
- väljastab `invoice_candidates.csv` ja `invoice_candidates.json`.

## Käivitamine

### Variant A: Outlooki kaudu

Kui `pypff/libpff` ei ole paigaldatud, saab Windowsis kasutada Outlooki enda COM-liidest:

```powershell
powershell -ExecutionPolicy Bypass -File .\scan_outlook_pst.ps1 -PstFile "C:\path\to\mail.pst" -OutDir ".\invoice_scan_output" -MaxMessages 1000
```

Soovitatav esimene proov:

```powershell
powershell -ExecutionPolicy Bypass -File .\scan_outlook_pst.ps1 -PstFile "C:\path\to\mail.pst" -OutDir ".\invoice_scan_output" -FromDate "2026-01-01" -ToDate "2026-01-31" -MaxMessages 5000
```

See variant ei salvesta manuseid, vaid loeb kirju ja manuste nimesid.

Kui tahad, et programm saaks PDF/XML arvetest summat, KM-i, IBAN-it ja kuupäevi lugeda, salvesta ainult arvekandidaatide manused:

```powershell
powershell -ExecutionPolicy Bypass -File .\scan_outlook_pst.ps1 -PstFile "C:\path\to\mail.pst" -OutDir ".\invoice_scan_output" -FromDate "2026-03-01" -ToDate "2026-03-31" -SaveCandidateAttachments
```

See ei salvesta kõiki PST manuseid, vaid ainult skoori läbinud kandidaatarvete PDF/XML/Excel/digikonteinereid.

### Variant B: otse PST parseriga

Lihtsaim viis sellest kaustast:

```powershell
powershell -ExecutionPolicy Bypass -File .\scan_pst.ps1 -PstFile "C:\path\to\mail.pst" -OutDir ".\invoice_scan_output"
```

Kui PowerShelli skripte saab sinu masinas otse käivitada:

```powershell
.\scan_pst.ps1 -PstFile "C:\path\to\mail.pst" -OutDir ".\invoice_scan_output"
```

Otse Pythoniga:

```powershell
& "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pst_invoice_finder.cli scan "C:\path\to\mail.pst" --out-dir "C:\path\to\invoice_scan_output"
```

Kui kasutad enda Pythonit:

```powershell
python -m pst_invoice_finder.cli scan "C:\path\to\mail.pst" --out-dir ".\invoice_scan_output"
```

## Oluline sõltuvus

PST otse lugemiseks on vaja `pypff` / `libpff` Python bindingut. Praeguses Codexi Pythoni komplektis seda ei olnud, seega adapter on valmis, aga päris `.pst` skannimiseks tuleb see sõltuvus Windowsis lisada.

Kui `pypff` on olemas, jääb käsk samaks.

## Tulemused

Väljundkaustas tekivad:

- `invoice_candidates.csv` - Excelis avatav kontrolltabel;
- `clean_invoice_candidates.csv` - puhastatud kontrolltabel, kus on duplikaadid ja meeldetuletused märgitud;
- `likely_invoices_only.csv` - unikaalsed kõige tõenäolisemad arved;
- `needs_review.csv` - võimalikud arved, mida tasub käsitsi vaadata;
- `reminders_and_debt_notices.csv` - meeldetuletused ja võlateatised eraldi;
- `invoice_candidates.json` - sama info masinloetavalt;
- `attachments/` - salvestatud manused, jaotatud kuude ning PST kaustade kaupa.

## Järgmised sammud

1. Lisada päris PST failiga test.
2. Täpsustada ERLIN-i tüüpiliste tarnijate ja arvefailide märksõnad.
3. Eraldada PDF/XML arvetest arve nr, kuupäev, tarnija, neto, KM ja bruto.
4. Lisada pangaväljavõtte import ja maksete sobitamine.

## Arvete kinnitamine andmebaasi

Pärast skänni saab arvekandidaadid käsitsi üle vaadata ja SQLite andmebaasi salvestada:

```powershell
powershell -ExecutionPolicy Bypass -File .\review_invoices.ps1 -InputCsv ".\invoice_scan_output\likely_invoices_only.csv" -DbPath ".\invoice_register.sqlite"
```

Valikud ülevaatuse ajal:

- `y` - kinnita, et see on päris ja õigustatud arve;
- `n` - märgi mittearveks/spämmiks;
- `s` - jäta hilisemaks;
- `e` - muuda enne salvestamist välju;
- `q` - lõpeta ülevaatus.

Kui sama arve tuleb järgmises skännis uuesti välja ja ta on juba varem kinnitatud, siis näitab programm seda staatusega `OK previously confirmed`. Seda saab samas ülevaatuses soovi korral muuta.

Andmebaasi Exceli jaoks CSV-ks eksportimine:

```powershell
powershell -ExecutionPolicy Bypass -File .\export_invoice_db.ps1 -DbPath ".\invoice_register.sqlite" -OutputCsv ".\invoice_register_export.csv"
```

## Brauseri kasutajaliides

Käivita lokaalne veebiliides:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_web_ui.ps1 -InputCsv ".\invoice_scan_output_outlook_refined\clean_invoice_candidates.csv" -DbPath ".\invoice_register.sqlite" -Port 8765
```

Seejärel ava brauseris:

```text
http://127.0.0.1:8765
```

Veebiliides lubab arveid otsida, filtreerida, kinnitada, tagasi lükata ning muuta arve nr, kuupäeva, väljastajat, maksmise rekvisiite ja summat.

## PDF/XML väljade lugemine

Kui skänn on tehtud lülitiga `-SaveCandidateAttachments`, saab väljad lugeda brauseris nupuga `Loe PDF/XML`.

Käsurealt saab sama teha nii:

```powershell
powershell -ExecutionPolicy Bypass -File .\extract_invoice_fields.ps1 -DbPath ".\invoice_register.sqlite" -Status pending
```

Loetavad väljad:

- summa;
- KM;
- IBAN / maksmise rekvisiidid;
- maksetähtaeg;
- arve tegelik kuupäev;
- väljastaja registrikood;
- väljastaja KMKR.

## Kinnitatud arvete arhiveerimine

Kinnitatud arvete failid saab kopeerida aasta ja kuu kaupa arhiivikaustadesse:

```powershell
powershell -ExecutionPolicy Bypass -File .\archive_confirmed_invoices.ps1 -DbPath ".\invoice_register.sqlite" -ArchiveRoot ".\confirmed_invoice_archive"
```

Kaustastruktuur:

```text
confirmed_invoice_archive/
  2026/
    03/
      ostuarved/
      muugiarved/
```

Käsu tulemusena tekib ka `archive_manifest.csv`, kus on kirjas, milline algfail kuhu kopeeriti.

Järgmised planeeritud moodulid:

- EMTA KMD/KMD INF XML/CSV eksport kinnitatud ostuarvete ja müügiarvete andmebaasi põhjal;
- pangaväljavõtte import ning arvete makstuks/maksmata sobitamine;
- Meriti jaoks makseinfo ettevalmistamine või API/importfaili tugi.
