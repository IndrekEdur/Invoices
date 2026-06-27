from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .bank_import import parse_statement, write_csv as write_bank_csv
from .compare_merit_bank_mail import best_match as best_merit_bank_match, compare as compare_merit_bank_mail, match_score_merit_bank
from .invoice_db import connect, get_invoice, get_settings, list_bank_transactions, set_settings, status_counts, update_status, upsert_bank_transactions, upsert_seen
from .invoice_extract import extract_for_db
from .invoice_project_lines import parse_project_lines_from_attachments
from .merit_api_client import MeritClient, MeritApiError
from .merit_api_payload import DEFAULT_GL_ACCOUNT_CODE, DEFAULT_ITEM_CODE, build_purchase_invoice_payload
from .reconcile_bank import reconcile as reconcile_bank
from .review_invoices import candidate_to_data, read_rows
from .sepa_payment import build_sepa_payment_xml


APP_HTML = r"""<!doctype html>
<html lang="et">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Arvete register</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <main class="shell">
    <div id="toast" class="toast hidden"></div>
    <aside class="side">
      <div class="brand">
        <div class="mark">AR</div>
        <div>
          <h1>Arvete register</h1>
          <p>PST skänni kontroll ja kinnitamine</p>
        </div>
      </div>

      <section class="stats" id="stats"></section>

      <section class="filters">
        <div>
          <div class="filterTitle">Vaade</div>
          <input id="viewMode" type="hidden" value="combined">
          <div id="viewButtons" class="viewButtons">
            <button type="button" data-view="combined" class="active">Koondlist</button>
            <button type="button" data-view="merit">Meriti list</button>
            <button type="button" data-view="mail">Maili list</button>
            <button type="button" data-view="project-missing">Projektita Meriti arved</button>
            <button type="button" data-view="bank-merit-check">Pank vs Merit</button>
            <button type="button" data-view="upload">Laadi arve fail</button>
            <button type="button" data-view="bank-upload">Laadi panga väljavõte</button>
            <button type="button" data-view="settings">Seadistus</button>
          </div>
        </div>
        <button type="button" id="sendMeritPaymentsBtn" class="sideAction">Märgi pangamaksed Meritis makstuks</button>
        <label>
          Staatus
          <select id="statusFilter">
            <option value="all">Kõik</option>
            <option value="pending">Ootel</option>
            <option value="confirmed">Kinnitatud</option>
            <option value="rejected">Tagasi lükatud</option>
          </select>
        </label>
        <label>
          Arve liik
          <select id="kindFilter">
            <option value="purchase_candidate" selected>Ostuarved</option>
            <option value="own_sales_invoice">ERLIN müügiarved</option>
            <option value="all">Kõik liigid</option>
          </select>
        </label>
        <label>
          Otsing
          <input id="searchBox" type="search" placeholder="Arve nr, väljastaja, pealkiri">
        </label>
        <label class="check">
          <input id="hideDuplicates" type="checkbox" checked>
          Peida duplikaadid
        </label>
      </section>
    </aside>

    <section class="listPane">
      <div class="toolbar">
        <div>
          <h2>Skänni tulemused</h2>
          <p id="resultCount">Laen...</p>
        </div>
        <button id="refreshBtn" class="iconBtn" title="Värskenda">↻</button>
      </div>
      <div id="reconciliationTable" class="tablePane"></div>
      <div id="invoiceList" class="invoiceList"></div>
      <form id="uploadPane" class="settingsPane hidden">
        <h2>Laadi arve fail käsitsi</h2>
        <p class="muted">See lisab faili arveregistrisse ilma Outlooki/PST skännita.</p>
        <div class="settingsGrid">
          <label>Arve fail<input name="invoice_file" type="file" accept=".pdf,.xml,.asice,.bdoc,.ddoc,.xlsx,.xls,.csv,.jpg,.jpeg,.png"></label>
          <label>Väljastaja<input name="issuer_name" placeholder="Tarnija nimi, kui tead"></label>
          <label>Arve nr<input name="invoice_number" placeholder="Kui tead"></label>
          <label>Arve kuupäev<input name="invoice_date" type="date"></label>
          <label>Märkus<textarea name="review_note" rows="3" placeholder="Näiteks kust fail saadi"></textarea></label>
        </div>
        <div class="actions">
          <button type="submit" class="save">Laadi üles ja lisa registrisse</button>
        </div>
        <div id="uploadStatus" class="settingsStatus"></div>
      </form>
      <form id="bankUploadPane" class="settingsPane hidden">
        <h2>Laadi panga väljavõte</h2>
        <p class="muted">Lae siia Swedbanki ISO XML / CAMT väljavõte. Uued kanded lisatakse andmebaasi, varem imporditud kanded jäetakse alles.</p>
        <div class="settingsGrid">
          <label>Panga väljavõte<input name="bank_statement_file" type="file" accept=".xml"></label>
        </div>
        <div class="actions">
          <button type="submit" class="save">Impordi panga väljavõte</button>
        </div>
        <div id="bankUploadStatus" class="settingsStatus"></div>
      </form>
      <section id="meritPaymentsPane" class="settingsPane hidden">
        <h2>Pangas makstud arved Meritisse</h2>
        <div class="actions periodActions"><label class="inlineControl">Periood<select id="meritPaymentsPeriod"><option value="current" selected>Jooksev kuu</option><option value="previous">Eelmine kuu</option><option value="last3">Viimased 3 kuud</option><option value="year">Jooksev aasta</option><option value="all">Kogu ajalugu</option></select></label></div>
        <p class="muted">Kontrolli read üle. Meritisse saadetakse makstuks märkimine ainult nendele arvetele, millel linnuke ees on.</p>
        <div class="actions">
          <button type="button" id="selectAllMeritPaymentsBtn">Vali kõik</button>
          <button type="button" id="clearMeritPaymentsBtn">Eemalda linnukesed</button>
          <button type="button" id="sendSelectedMeritPaymentsBtn" class="save">Saada valitud maksed Meritisse</button>
        </div>
        <div id="meritPaymentsStatus" class="settingsStatus"></div>
        <div id="meritPaymentsLog" class="tablePane staticTable"></div>
        <div id="meritPaymentsTable" class="tablePane staticTable"></div>
      </section>
      <section id="projectMissingPane" class="settingsPane hidden">
        <h2>Projektita Meriti arved</h2>
        <p class="muted">Kontrollib Meriti ostuarveid ja leiab arved, millel projekti dimensiooni kood puudub.</p>
        <div class="actions">
          <button type="button" id="loadProjectMissingBtn" class="save">Kontrolli Meritist</button>
        </div>
        <div id="projectMissingStatus" class="settingsStatus"></div>
        <div id="projectMissingTable" class="tablePane staticTable"></div>
      </section>
      <section id="bankMeritPane" class="settingsPane hidden">
        <h2>Panga maksed vs Meriti arved</h2>
        <div class="actions periodActions"><label class="inlineControl">Periood<select id="bankMeritPeriod"><option value="current">Jooksev kuu</option><option value="previous">Eelmine kuu</option><option value="last3" selected>Viimased 3 kuud</option><option value="year">Jooksev aasta</option><option value="all">Kogu ajalugu</option></select></label></div>
        <p class="muted">Võrdleb imporditud pangakandeid Meriti ostuarvetega ning toob välja vastuolud.</p>
        <div class="actions">
          <button type="button" id="loadBankMeritBtn" class="save">Kontrolli pank vs Merit</button>
        </div>
        <div id="bankMeritStatus" class="settingsStatus"></div>
        <div id="bankMeritTable" class="tablePane staticTable"></div>
      </section>
      <form id="settingsPane" class="settingsPane hidden">
        <h2>Seadistus</h2>
        <h3>Panga maksefail</h3>
        <div class="settingsGrid">
          <label>Maksja nimi<input name="payment_debtor_name" placeholder="ERLIN OÜ"></label>
          <label>Maksja IBAN<input name="payment_debtor_iban" placeholder="EE..."></label>
        </div>
        <h3>Meriti API</h3>
        <div class="settingsGrid">
          <label>API ID<input name="merit_api_id" autocomplete="off"></label>
          <label>API võti<input name="merit_api_key" type="password" autocomplete="off" placeholder="Jäta tühjaks, kui ei muuda"></label>
          <label>Vaikimisi KM määr<select name="merit_default_tax_pct"><option value="24">24%</option><option value="22">22%</option><option value="20">20%</option><option value="13">13%</option><option value="9">9%</option><option value="0">0%</option></select></label>
          <label>Kuluartikkel / Item.Code<input name="merit_default_item_code" placeholder="alltöö"></label>
          <label>Konto / GLAccountCode<input name="merit_default_gl_account_code" placeholder="4009"></label>
          <label>Makseviis<input name="merit_payment_method" placeholder="Pank"></label>
          <label>Projekti DimId<input name="merit_project_dimension_id" placeholder="Tühi = otsib nime järgi Projekt"></label>
        </div>
        <div class="actions">
          <button type="submit" class="save">Salvesta seadistus</button>
          <button type="button" id="testMeritBtn">Testi ühendust</button>
        </div>
        <div id="settingsStatus" class="settingsStatus"></div>
      </form>
    </section>

    <section class="detailPane">
      <div id="emptyDetail" class="empty">
        <h2>Vali arve</h2>
        <p>Siin saad andmeid parandada ning märkida arve kinnitatuks või mittearveks.</p>
      </div>

      <form id="detailForm" class="detail hidden">
        <div class="detailHeader">
          <div>
            <span id="statusPill" class="pill">Ootel</span>
            <h2 id="detailTitle">Arve</h2>
          </div>
          <span id="seenInfo" class="seen"></span>
        </div>

        <div class="grid">
          <label>Arve nr<input name="invoice_number"></label>
          <label>Kuupäev<input name="invoice_date" type="date"></label>
          <label>Väljastaja<input name="issuer_name"></label>
          <label>E-post<input name="issuer_email"></label>
          <label>Arve liik<select name="invoice_kind"><option value="purchase_candidate">Ostuarve kandidaat</option><option value="own_sales_invoice">ERLIN müügiarve</option></select></label>
          <label>Summa<input name="amount_total" inputmode="decimal"></label>
          <label>KM<input name="vat_amount" inputmode="decimal"></label>
          <label>Maksetähtaeg<input name="due_date" type="date"></label>
          <label>Registrikood<input name="issuer_reg_code"></label>
          <label>KMKR<input name="issuer_vat_no"></label>
          <label>Valuuta<input name="currency"></label>
        </div>

        <label>Maksmise rekvisiidid<textarea name="payment_details" rows="3"></textarea></label>
        <label>Märkus<textarea name="review_note" rows="3"></textarea></label>

        <div class="meta">
          <div><strong>Pealkiri</strong><span id="metaSubject"></span></div>
          <div><strong>Manused</strong><span id="metaAttachments"></span></div>
          <div><strong>Salvestatud failid</strong><span id="metaPaths"></span></div>
          <div><strong>PDF/XML lugemine</strong><span id="metaExtraction"></span></div>
          <div><strong>Makse staatus</strong><span id="metaPayment"></span></div>
          <div><strong>Allikas</strong><span id="metaSource"></span></div>
        </div>

        <div class="actions">
          <button type="button" id="confirmBtn" class="confirm">✓ Kinnita</button>
          <button type="button" id="rejectBtn" class="reject">× Ei ole arve</button>
          <button type="button" id="pendingBtn">○ Jäta ootele</button>
          <button type="button" id="extractBtn">Loe PDF/XML</button>
          <button type="button" id="meritPreviewBtn">Merit JSON eelvaade</button>
          <button type="button" id="paymentFileBtn">Koosta panga maksefail</button>
          <button type="submit" class="save">Salvesta väljad</button>
        </div>
      </form>

      <section id="meritPreview" class="meritPreview hidden">
        <div class="detailHeader">
          <div>
            <span class="pill kind">Merit API</span>
            <h2>Meritisse saadetav ostuarve</h2>
          </div>
        </div>
        <div id="meritHuman" class="humanPreview"></div>
        <div id="meritWarnings" class="warningBox"></div>
        <div class="actions">
          <button type="button" id="sendMeritBtn" class="confirm">Saada arve Meritisse</button>
          <button type="button" id="resendMeritBtn" class="reject">Saada uuesti Meritisse</button>
        </div>
        <div id="meritSendStatus" class="settingsStatus hidden"></div>
        <h3>JSON eelvaade</h3>
        <pre id="meritJson"></pre>
      </section>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
"""


APP_CSS = r"""
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; font-family: Segoe UI, Arial, sans-serif; color: #17202a; background: #f5f7f8; }
button, input, select, textarea { font: inherit; }
.shell { min-height: 100vh; display: grid; grid-template-columns: 280px minmax(420px, 1fr) minmax(420px, 560px); }
.side { background: #17324d; color: #f8fbfd; padding: 24px; display: flex; flex-direction: column; gap: 24px; }
.brand { display: flex; gap: 12px; align-items: center; }
.mark { width: 44px; height: 44px; display: grid; place-items: center; border-radius: 6px; background: #f2b84b; color: #17202a; font-weight: 800; }
h1, h2, p { margin: 0; }
.brand h1 { font-size: 20px; }
.brand p { color: #c8d6df; font-size: 13px; margin-top: 4px; }
.stats { display: grid; gap: 8px; }
.stat { display: flex; justify-content: space-between; padding: 12px; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.14); border-radius: 6px; }
.stat strong { font-size: 18px; }
.filters { display: grid; gap: 14px; }
.filterTitle { margin-bottom: 6px; font-size: 13px; font-weight: 650; }
.viewButtons { display: grid; gap: 7px; }
.viewButtons button, .sideAction { width: 100%; border: 1px solid rgba(255,255,255,.18); border-radius: 6px; padding: 10px 11px; background: rgba(255,255,255,.08); color: #f8fbfd; cursor: pointer; text-align: left; font-weight: 750; }
.viewButtons button:hover, .viewButtons button.active { background: #f8fbfd; color: #17324d; border-color: #f8fbfd; }
.sideAction { background: #f2b84b; border-color: #f2b84b; color: #17202a; text-align: center; }
.sideAction:hover { filter: brightness(1.04); }
label { display: grid; gap: 6px; font-size: 13px; font-weight: 650; color: inherit; }
input, select, textarea { width: 100%; border: 1px solid #cfd9df; border-radius: 6px; padding: 10px 11px; background: #fff; color: #17202a; }
.side input, .side select { border-color: transparent; }
.check { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.check input { width: auto; }
.listPane { border-right: 1px solid #dce3e7; background: #fff; min-width: 0; }
.toolbar { height: 82px; display: flex; align-items: center; justify-content: space-between; padding: 18px 20px; border-bottom: 1px solid #e2e8ec; }
.toolbar h2, .detailHeader h2 { font-size: 20px; }
.toolbar p { color: #6b7883; margin-top: 4px; font-size: 13px; }
.iconBtn { width: 38px; height: 38px; border-radius: 6px; border: 1px solid #cfd9df; background: #fff; cursor: pointer; }
.invoiceList { height: calc(100vh - 82px); overflow: auto; }
.tablePane { height: calc(100vh - 82px); overflow: auto; display: none; }
.tablePane.staticTable { display: block; height: auto; max-height: calc(100vh - 240px); border: 1px solid #dce3e7; border-radius: 6px; }
.settingsPane { height: calc(100vh - 82px); overflow: auto; display: grid; align-content: start; gap: 18px; padding: 20px; }
.settingsPane.hidden { display: none; }
.settingsPane h3 { margin: 2px 0 -6px; font-size: 14px; color: #34424e; }
.settingsGrid { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 14px; max-width: 820px; }
.settingsStatus { max-width: 820px; padding: 12px; border-radius: 6px; background: #eef3f1; color: #34424e; font-size: 13px; white-space: pre-wrap; }
.progressBox { display: grid; gap: 7px; }
.progressMeta { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; color: #52606b; }
.progressTrack { height: 8px; background: #dbe7ef; border-radius: 999px; overflow: hidden; }
.progressFill { height: 100%; width: 0%; background: #173a59; border-radius: 999px; transition: width .35s ease; }
.dataTable { width: 100%; border-collapse: collapse; font-size: 13px; }
.dataTable th { position: sticky; top: 0; z-index: 1; background: #edf3f6; color: #263642; text-align: left; padding: 10px 12px; border-bottom: 1px solid #cfd9df; white-space: nowrap; }
.dataTable .filterRow th { top: 39px; background: #f7fafb; padding: 7px 8px; }
.dataTable .filterRow input, .dataTable .filterRow select { min-width: 92px; padding: 6px 7px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.dataTable .filterRow .narrowFilter { min-width: 74px; }
.dataTable td { padding: 9px 12px; border-bottom: 1px solid #edf1f3; vertical-align: top; }
.dataTable tr:hover { background: #f7faf9; }
.dataTable .clickableRow { cursor: pointer; }
.yes { color: #12613b; font-weight: 800; }
.no { color: #8a2430; font-weight: 800; }
.muted { color: #6b7883; }
.nowrap { white-space: nowrap; }
.row { width: 100%; text-align: left; border: 0; border-bottom: 1px solid #edf1f3; background: #fff; padding: 14px 18px; display: grid; gap: 8px; cursor: pointer; }
.row:hover, .row.active { background: #f0f6f4; }
.rowTop { display: flex; gap: 10px; align-items: center; justify-content: space-between; }
.subject { font-weight: 750; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.issuer { color: #52606b; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rowMeta { display: flex; gap: 8px; flex-wrap: wrap; color: #6b7883; font-size: 12px; }
.pill { display: inline-flex; align-items: center; min-height: 24px; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 750; border: 1px solid transparent; white-space: nowrap; }
.pill.pending { color: #775300; background: #fff3cc; border-color: #f3d676; }
.pill.confirmed { color: #12613b; background: #dff5ea; border-color: #9bd6b8; }
.pill.rejected { color: #8a2430; background: #fae2e5; border-color: #e7a7ae; }
.pill.duplicate { color: #44515c; background: #eef2f4; border-color: #d6dee3; }
.pill.kind { color: #264b6a; background: #e4f0f8; border-color: #b8d4e8; }
.pill.paid { color: #12613b; background: #dff5ea; border-color: #9bd6b8; }
.pill.unmatched, .pill.unknown { color: #775300; background: #fff3cc; border-color: #f3d676; }
.detailPane { padding: 24px; overflow: auto; }
.empty { min-height: 220px; display: grid; align-content: center; gap: 8px; color: #53616c; }
.empty h2 { color: #17202a; }
.hidden { display: none; }
.toast { position: fixed; top: 14px; left: 50%; transform: translateX(-50%); z-index: 10; max-width: min(680px, calc(100vw - 28px)); padding: 10px 14px; border-radius: 6px; background: #17324d; color: #fff; box-shadow: 0 8px 24px rgba(23,50,77,.24); font-size: 14px; font-weight: 650; }
.detail { display: grid; gap: 18px; }
.detail.hidden { display: none; }
.detailHeader { display: flex; align-items: start; justify-content: space-between; gap: 18px; padding-bottom: 14px; border-bottom: 1px solid #dce3e7; }
.detailHeader h2 { margin-top: 8px; line-height: 1.25; }
.seen { color: #6b7883; font-size: 13px; text-align: right; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
textarea { resize: vertical; }
.meta { display: grid; gap: 10px; padding: 14px; background: #eef3f1; border-radius: 6px; color: #44515c; font-size: 13px; }
.meta div { display: grid; gap: 4px; }
.meta span { overflow-wrap: anywhere; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; border-top: 1px solid #dce3e7; padding-top: 16px; }
.periodActions { margin-bottom: 8px; }
.inlineControl { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; color: #173a59; }
.inlineControl select { min-width: 170px; }
.actions button { border: 1px solid #cfd9df; background: #fff; border-radius: 6px; padding: 10px 13px; cursor: pointer; font-weight: 750; }
.actions .confirm { background: #1f7a4d; border-color: #1f7a4d; color: #fff; }
.actions .reject { background: #a83242; border-color: #a83242; color: #fff; }
.actions .save { background: #17324d; border-color: #17324d; color: #fff; margin-left: auto; }
.smallAction { border: 1px solid #cfd9df; background: #fff; border-radius: 4px; padding: 6px 8px; cursor: pointer; font-size: 12px; font-weight: 750; white-space: nowrap; }
.smallAction:hover { background: #eef3f1; }
.meritPreview { display: grid; gap: 14px; }
.meritPreview.hidden { display: none; }
.meritPreview h3 { margin: 0; font-size: 14px; color: #34424e; }
.humanPreview { display: grid; gap: 14px; }
.humanGroup { border: 1px solid #dce3e7; border-radius: 6px; background: #fff; overflow: hidden; }
.humanGroup h3 { padding: 10px 12px; background: #edf3f6; border-bottom: 1px solid #dce3e7; }
.humanRows { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.humanRow { display: grid; gap: 3px; padding: 10px 12px; border-bottom: 1px solid #edf1f3; min-width: 0; }
.humanRow strong { color: #52606b; font-size: 12px; }
.humanRow span { overflow-wrap: anywhere; font-weight: 650; }
.meritPreview pre { margin: 0; padding: 14px; background: #111827; color: #e5edf5; border-radius: 6px; overflow: auto; max-height: calc(100vh - 210px); font-size: 12px; line-height: 1.45; }
.warningBox { display: grid; gap: 6px; padding: 12px; border: 1px solid #f0cd72; background: #fff8df; border-radius: 6px; color: #624700; font-size: 13px; }
@media (max-width: 1100px) {
  .shell { grid-template-columns: 240px 1fr; }
  .detailPane { grid-column: 1 / -1; border-top: 1px solid #dce3e7; }
  .invoiceList { height: 54vh; }
}
@media (max-width: 760px) {
  .shell { display: block; }
  .side { padding: 18px; }
  .grid { grid-template-columns: 1fr; }
  .invoiceList { height: auto; max-height: 60vh; }
  .actions .save { margin-left: 0; }
}
"""


APP_JS = r"""
let invoices = [];
let reconciliation = { combined: [], merit: [], mail: [] };
let currentCounts = {};
let meritPaymentCandidates = [];
let projectMissingRows = [];
let bankMeritRows = [];
let columnFilters = {
  invoice_date: '',
  supplier: '',
  invoice_number: '',
  amount: '',
  exists_merit: 'all',
  exists_mail: 'all',
  exists_bank: 'all',
  merit_payment_status: 'all',
  bank_payment_status: 'all',
  bank_match: '',
  source: 'all'
};
let selectedId = null;

const els = {
  list: document.getElementById('invoiceList'),
  reconciliationTable: document.getElementById('reconciliationTable'),
  uploadPane: document.getElementById('uploadPane'),
  uploadStatus: document.getElementById('uploadStatus'),
  bankUploadPane: document.getElementById('bankUploadPane'),
  bankUploadStatus: document.getElementById('bankUploadStatus'),
  meritPaymentsPane: document.getElementById('meritPaymentsPane'),
  meritPaymentsStatus: document.getElementById('meritPaymentsStatus'),
  meritPaymentsLog: document.getElementById('meritPaymentsLog'),
  meritPaymentsTable: document.getElementById('meritPaymentsTable'),
  meritPaymentsPeriod: document.getElementById('meritPaymentsPeriod'),
  projectMissingPane: document.getElementById('projectMissingPane'),
  projectMissingStatus: document.getElementById('projectMissingStatus'),
  projectMissingTable: document.getElementById('projectMissingTable'),
  bankMeritPane: document.getElementById('bankMeritPane'),
  bankMeritStatus: document.getElementById('bankMeritStatus'),
  bankMeritTable: document.getElementById('bankMeritTable'),
  bankMeritPeriod: document.getElementById('bankMeritPeriod'),
  settingsPane: document.getElementById('settingsPane'),
  settingsStatus: document.getElementById('settingsStatus'),
  stats: document.getElementById('stats'),
  count: document.getElementById('resultCount'),
  viewMode: document.getElementById('viewMode'),
  viewButtons: document.getElementById('viewButtons'),
  status: document.getElementById('statusFilter'),
  kind: document.getElementById('kindFilter'),
  search: document.getElementById('searchBox'),
  hideDuplicates: document.getElementById('hideDuplicates'),
  form: document.getElementById('detailForm'),
  empty: document.getElementById('emptyDetail'),
  title: document.getElementById('detailTitle'),
  statusPill: document.getElementById('statusPill'),
  seen: document.getElementById('seenInfo'),
  metaSubject: document.getElementById('metaSubject'),
  metaAttachments: document.getElementById('metaAttachments'),
  metaPaths: document.getElementById('metaPaths'),
  metaExtraction: document.getElementById('metaExtraction'),
  metaPayment: document.getElementById('metaPayment'),
  metaSource: document.getElementById('metaSource'),
  meritPreview: document.getElementById('meritPreview'),
  meritHuman: document.getElementById('meritHuman'),
  meritWarnings: document.getElementById('meritWarnings'),
  meritJson: document.getElementById('meritJson'),
  meritSendStatus: document.getElementById('meritSendStatus'),
  toast: document.getElementById('toast')
};

function statusLabel(status) {
  return { pending: 'Ootel', confirmed: 'Kinnitatud', rejected: 'Tagasi lükatud' }[status] || status;
}

function kindLabel(kind) {
  return { purchase_candidate: 'Ostuarve', own_sales_invoice: 'ERLIN müügiarve' }[kind] || kind || 'Ostuarve';
}

function paymentLabel(status) {
  return { paid: 'Makstud', unmatched: 'Pangavasteta', unknown: 'Kontrollimata' }[status] || status || 'Kontrollimata';
}

function renderStats(counts) {
  if (els.viewMode.value !== 'mail') {
    const rows = filteredReconciliation();
    const withMerit = rows.filter(row => row.exists_merit).length;
    const withMail = rows.filter(row => row.exists_mail).length;
    const withBank = rows.filter(row => row.exists_bank).length;
    els.stats.innerHTML = [
      ['Ridu', rows.length],
      ['Meritis', withMerit],
      ['Mailis', withMail],
      ['Pangas', withBank]
    ].map(([label, value]) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`).join('');
    return;
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  els.stats.innerHTML = [
    ['Kokku', total],
    ['Ootel', counts.pending || 0],
    ['Kinnitatud', counts.confirmed || 0],
    ['Tagasi lükatud', counts.rejected || 0]
  ].map(([label, value]) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`).join('');
}

function filtered() {
  const status = els.status.value;
  const kind = els.kind.value;
  const query = els.search.value.trim().toLowerCase();
  return invoices.filter(inv => {
    if (status !== 'all' && inv.status !== status) return false;
    if (kind !== 'all' && (inv.invoice_kind || 'purchase_candidate') !== kind) return false;
    if (els.hideDuplicates.checked && inv.is_duplicate === 'true') return false;
    if (!query) return true;
    return [inv.invoice_number, inv.issuer_name, inv.subject, inv.attachment_names]
      .join(' ')
      .toLowerCase()
      .includes(query);
  });
}

function filteredReconciliation() {
  const query = els.search.value.trim().toLowerCase();
  const rows = reconciliation[els.viewMode.value] || [];
  return rows.filter(row => {
    if (query && ![
    row.invoice_number, row.invoice_date, row.supplier, row.amount,
    row.merit_payment_status, row.bank_payment_status, row.bank_party,
    row.bank_remittance, row.source
    ].join(' ').toLowerCase().includes(query)) return false;

    for (const key of ['invoice_date', 'supplier', 'invoice_number', 'amount']) {
      const value = columnFilters[key].trim().toLowerCase();
      if (value && !String(row[key] || '').toLowerCase().includes(value)) return false;
    }

    for (const key of ['exists_merit', 'exists_mail', 'exists_bank']) {
      const value = columnFilters[key];
      if (value !== 'all' && Boolean(row[key]) !== (value === 'yes')) return false;
    }

    for (const key of ['merit_payment_status', 'bank_payment_status', 'source']) {
      const value = columnFilters[key];
      if (value !== 'all' && String(row[key] || '') !== value) return false;
    }

    const bankMatch = columnFilters.bank_match.trim().toLowerCase();
    if (bankMatch && ![
      row.bank_date, row.bank_amount, row.bank_party, row.bank_remittance
    ].join(' ').toLowerCase().includes(bankMatch)) return false;

    return true;
  });
}

function boolCell(value) {
  return value ? '<span class="yes">jah</span>' : '<span class="no">ei</span>';
}

function paymentText(status) {
  return {
    paid: 'makstud',
    partially_paid: 'osaliselt makstud',
    unpaid: 'maksmata',
    unknown: 'kontrollimata',
    unmatched: 'pangavasteta',
    no_bank_match: 'pangas vastet ei leitud',
    bank_debit_no_merit: 'pangakanne, Meritis puudub'
  }[status] || status || '';
}

function startProgress(statusEl, steps, options = {}) {
  const started = Date.now();
  let percent = 2;
  let stepIndex = 0;
  const maxBeforeDone = options.maxBeforeDone || 92;
  const render = () => {
    const elapsed = Math.floor((Date.now() - started) / 1000);
    const step = steps[Math.min(stepIndex, steps.length - 1)] || 'Töötlen...';
    statusEl.innerHTML = `
      <div class="progressBox">
        <div>${escapeHtml(step)}</div>
        <div class="progressTrack"><div class="progressFill" style="width:${Math.round(percent)}%"></div></div>
        <div class="progressMeta"><span>u ${Math.round(percent)}%</span><span>${elapsed}s</span></div>
      </div>`;
  };
  render();
  const timer = window.setInterval(() => {
    const elapsed = Math.floor((Date.now() - started) / 1000);
    if (steps.length > 1 && elapsed > (stepIndex + 1) * (options.secondsPerStep || 8) && stepIndex < steps.length - 1) {
      stepIndex += 1;
    }
    const increment = percent < 45 ? 4 : percent < 75 ? 2 : 0.7;
    percent = Math.min(maxBeforeDone, percent + increment);
    render();
  }, 1000);
  return {
    done(message) {
      window.clearInterval(timer);
      statusEl.innerHTML = `
        <div class="progressBox">
          <div>${escapeHtml(message)}</div>
          <div class="progressTrack"><div class="progressFill" style="width:100%"></div></div>
          <div class="progressMeta"><span>100%</span><span>${Math.floor((Date.now() - started) / 1000)}s</span></div>
        </div>`;
    },
    fail(message) {
      window.clearInterval(timer);
      statusEl.textContent = message;
    }
  };
}

async function fetchJsonWithProgress(url, statusEl, steps, options = {}) {
  const progress = startProgress(statusEl, steps, options);
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs || 60000;
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const fetchOptions = { ...(options.fetchOptions || {}), signal: controller.signal };
    const res = await fetch(url, fetchOptions);
    window.clearTimeout(timeout);
    const payload = await res.json();
    if (payload.error) {
      progress.fail(payload.error);
    }
    return { payload, progress };
  } catch (err) {
    window.clearTimeout(timeout);
    const message = err.name === 'AbortError'
      ? `Päring ei vastanud ${Math.round(timeoutMs / 1000)} sekundiga. Värskenda lehte ja proovi uuesti; kui kordub, taaskäivita server.`
      : `Päring ebaõnnestus: ${err.message || err}`;
    progress.fail(message);
    return { payload: { error: err.message || String(err) }, progress };
  }
}

function periodQuery(selectEl) {
  return `period=${encodeURIComponent(selectEl?.value || 'current')}`;
}

function filterInput(key, placeholder, extraClass = '') {
  return `<input class="${extraClass}" data-filter="${key}" value="${escapeHtml(columnFilters[key] || '')}" placeholder="${placeholder}">`;
}

function filterSelect(key, options, extraClass = '') {
  return `<select class="${extraClass}" data-filter="${key}">
    ${options.map(([value, label]) => `<option value="${escapeHtml(value)}"${columnFilters[key] === value ? ' selected' : ''}>${escapeHtml(label)}</option>`).join('')}
  </select>`;
}

function renderReconciliationTable() {
  const rows = filteredReconciliation();
  els.count.textContent = `${rows.length} rida nähtaval`;
  els.reconciliationTable.innerHTML = `<table class="dataTable">
    <thead>
      <tr>
        <th>Kuupäev</th><th>Tarnija</th><th>Arve nr</th><th>Summa</th>
        <th>Meritis</th><th>Mailis</th><th>Pangas</th>
        <th>Meriti makse</th><th>Panga makse</th><th>Panga vaste</th><th>Allikas</th><th>Tegevus</th>
      </tr>
      <tr class="filterRow">
        <th>${filterInput('invoice_date', '2026-03', 'narrowFilter')}</th>
        <th>${filterInput('supplier', 'tarnija')}</th>
        <th>${filterInput('invoice_number', 'nr')}</th>
        <th>${filterInput('amount', 'summa', 'narrowFilter')}</th>
        <th>${filterSelect('exists_merit', [['all', 'kõik'], ['yes', 'jah'], ['no', 'ei']], 'narrowFilter')}</th>
        <th>${filterSelect('exists_mail', [['all', 'kõik'], ['yes', 'jah'], ['no', 'ei']], 'narrowFilter')}</th>
        <th>${filterSelect('exists_bank', [['all', 'kõik'], ['yes', 'jah'], ['no', 'ei']], 'narrowFilter')}</th>
        <th>${filterSelect('merit_payment_status', [['all', 'kõik'], ['paid', 'makstud'], ['partially_paid', 'osaline'], ['unpaid', 'maksmata'], ['unknown', 'kontrollimata']], 'narrowFilter')}</th>
        <th>${filterSelect('bank_payment_status', [['all', 'kõik'], ['paid', 'makstud'], ['unmatched', 'vasteta'], ['unknown', 'kontrollimata'], ['no_bank_match', 'vastet ei leitud'], ['bank_debit_no_merit', 'puudub Meritis']], 'narrowFilter')}</th>
        <th>${filterInput('bank_match', 'pank / selgitus')}</th>
        <th>${filterSelect('source', [['all', 'kõik'], ['Merit', 'Merit'], ['Mail', 'Mail'], ['Pank', 'Pank']], 'narrowFilter')}</th>
        <th></th>
      </tr>
    </thead>
    <tbody>${rows.map(row => `<tr class="${row.mail_invoice_id ? 'clickableRow' : ''}" ${row.mail_invoice_id ? `data-invoice-id="${escapeHtml(row.mail_invoice_id)}"` : ''}>
      <td class="nowrap">${escapeHtml(row.invoice_date || '')}</td>
      <td>${escapeHtml(row.supplier || '')}</td>
      <td class="nowrap">${escapeHtml(row.invoice_number || '')}</td>
      <td class="nowrap">${escapeHtml(row.amount || '')}</td>
      <td>${boolCell(row.exists_merit)}</td>
      <td>${boolCell(row.exists_mail)}</td>
      <td>${boolCell(row.exists_bank)}</td>
      <td>${escapeHtml(paymentText(row.merit_payment_status))}</td>
      <td>${escapeHtml(paymentText(row.bank_payment_status))}</td>
      <td>${escapeHtml([row.bank_date, row.bank_amount, row.bank_party].filter(Boolean).join(' · '))}<div class="muted">${escapeHtml(row.bank_remittance || '')}</div></td>
      <td class="nowrap">${escapeHtml(row.source || '')}</td>
      <td>${row.mail_invoice_id ? `<button class="smallAction openInvoiceBtn" data-invoice-id="${escapeHtml(row.mail_invoice_id)}">Ava</button> <button class="smallAction meritRowBtn" data-invoice-id="${escapeHtml(row.mail_invoice_id)}">JSON</button>` : ''}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function updateViewButtons() {
  els.viewButtons.querySelectorAll('[data-view]').forEach(button => {
    button.classList.toggle('active', button.dataset.view === els.viewMode.value);
  });
}

function setViewMode(view) {
  els.viewMode.value = view;
  renderCurrentView();
}

function renderCurrentView() {
  updateViewButtons();
  const isMail = els.viewMode.value === 'mail';
  const isSettings = els.viewMode.value === 'settings';
  const isUpload = els.viewMode.value === 'upload';
  const isBankUpload = els.viewMode.value === 'bank-upload';
  const isMeritPayments = els.viewMode.value === 'merit-payments';
  const isProjectMissing = els.viewMode.value === 'project-missing';
  const isBankMerit = els.viewMode.value === 'bank-merit-check';
  els.status.disabled = !isMail;
  els.kind.disabled = !isMail;
  els.hideDuplicates.disabled = !isMail;
  els.list.style.display = isMail ? 'block' : 'none';
  els.reconciliationTable.style.display = (!isMail && !isSettings && !isUpload && !isBankUpload && !isMeritPayments && !isProjectMissing && !isBankMerit) ? 'block' : 'none';
  els.uploadPane.classList.toggle('hidden', !isUpload);
  els.bankUploadPane.classList.toggle('hidden', !isBankUpload);
  els.meritPaymentsPane.classList.toggle('hidden', !isMeritPayments);
  els.projectMissingPane.classList.toggle('hidden', !isProjectMissing);
  els.bankMeritPane.classList.toggle('hidden', !isBankMerit);
  els.settingsPane.classList.toggle('hidden', !isSettings);
  if (isUpload) {
    els.count.textContent = 'Käsitsi üleslaadimine';
    renderStats({});
    els.form.classList.add('hidden');
    els.meritPreview.classList.add('hidden');
    els.empty.classList.remove('hidden');
    return;
  }
  if (isBankUpload) {
    els.count.textContent = 'Panga väljavõtte import';
    renderStats({});
    els.form.classList.add('hidden');
    els.meritPreview.classList.add('hidden');
    els.empty.classList.remove('hidden');
    return;
  }
  if (isMeritPayments) {
    els.count.textContent = 'Meriti maksete kinnitamine';
    renderStats({});
    els.form.classList.add('hidden');
    els.meritPreview.classList.add('hidden');
    els.empty.classList.remove('hidden');
    return;
  }
  if (isSettings) {
    els.count.textContent = 'Meriti API ühenduse seadistus';
    renderStats({});
    els.form.classList.add('hidden');
    els.meritPreview.classList.add('hidden');
    els.empty.classList.remove('hidden');
    loadSettings();
    return;
  }
  if (isMail) {
    renderStats(currentCounts);
    renderList();
  } else {
    renderStats({});
    renderReconciliationTable();
    els.form.classList.add('hidden');
    els.meritPreview.classList.add('hidden');
    els.empty.classList.remove('hidden');
  }
}

async function loadSettings() {
  const res = await fetch('/api/merit/settings');
  const settings = await res.json();
  els.settingsPane.elements.payment_debtor_name.value = settings.payment_debtor_name || 'ERLIN OÜ';
  els.settingsPane.elements.payment_debtor_iban.value = settings.payment_debtor_iban || '';
  els.settingsPane.elements.merit_api_id.value = settings.merit_api_id || '';
  els.settingsPane.elements.merit_api_key.value = '';
  els.settingsPane.elements.merit_default_tax_pct.value = settings.merit_default_tax_pct || '24';
  els.settingsPane.elements.merit_default_item_code.value = settings.merit_default_item_code || 'alltöö';
  els.settingsPane.elements.merit_default_gl_account_code.value = settings.merit_default_gl_account_code || '4009';
  els.settingsPane.elements.merit_payment_method.value = settings.merit_payment_method || 'Pank';
  els.settingsPane.elements.merit_project_dimension_id.value = settings.merit_project_dimension_id || '';
  els.settingsStatus.textContent = settings.has_api_key ? 'API võti on salvestatud. Võtit ei kuvata turvalisuse tõttu.' : 'API võtit pole veel salvestatud.';
}

function settingsPayload() {
  return {
    payment_debtor_name: els.settingsPane.elements.payment_debtor_name.value,
    payment_debtor_iban: els.settingsPane.elements.payment_debtor_iban.value,
    merit_api_id: els.settingsPane.elements.merit_api_id.value,
    merit_api_key: els.settingsPane.elements.merit_api_key.value,
    merit_default_tax_pct: els.settingsPane.elements.merit_default_tax_pct.value,
    merit_default_item_code: els.settingsPane.elements.merit_default_item_code.value,
    merit_default_gl_account_code: els.settingsPane.elements.merit_default_gl_account_code.value,
    merit_payment_method: els.settingsPane.elements.merit_payment_method.value,
    merit_project_dimension_id: els.settingsPane.elements.merit_project_dimension_id.value
  };
}

async function saveSettings() {
  const res = await fetch('/api/merit/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settingsPayload())
  });
  const payload = await res.json();
  els.settingsStatus.textContent = payload.message || 'Seadistus salvestatud.';
  els.settingsPane.elements.merit_api_key.value = '';
}

async function testMeritConnection() {
  els.settingsStatus.textContent = 'Testin ühendust Meritiga...';
  await saveSettings();
  const res = await fetch('/api/merit/test', { method: 'POST' });
  const payload = await res.json();
  if (payload.ok) {
    els.settingsStatus.textContent = `Ühendus töötab. KM määrasid leitud: ${payload.tax_count}.`;
  } else {
    els.settingsStatus.textContent = `Ühenduse test ebaõnnestus: ${payload.error || 'tundmatu viga'}`;
  }
}

function renderList() {
  const rows = filtered();
  els.count.textContent = `${rows.length} rida nähtaval`;
  els.list.innerHTML = rows.map(inv => {
    const duplicate = inv.is_duplicate === 'true' ? '<span class="pill duplicate">Duplikaat</span>' : '';
    const kind = `<span class="pill kind">${kindLabel(inv.invoice_kind)}</span>`;
    const source = inv.import_source === 'manual_upload' ? '<span class="pill kind">Käsitsi</span>' : '';
    const payment = `<span class="pill ${inv.payment_status || 'unknown'}">${paymentLabel(inv.payment_status)}</span>`;
    const active = inv.id === selectedId ? ' active' : '';
    return `<button class="row${active}" data-id="${inv.id}">
      <div class="rowTop">
        <span class="subject">${escapeHtml(inv.subject || '(pealkiri puudub)')}</span>
        <span class="pill ${inv.status}">${statusLabel(inv.status)}</span>
      </div>
      <div class="issuer">${escapeHtml(inv.issuer_name || '')} ${escapeHtml(inv.invoice_number || '')}</div>
      <div class="rowMeta">
        <span>${escapeHtml(inv.invoice_date || '')}</span>
        <span>${escapeHtml(inv.amount_total || '')} ${escapeHtml(inv.currency || '')}</span>
        <span>leitud ${inv.seen_count || 1}x</span>
        ${kind}
        ${source}
        ${payment}
        ${duplicate}
      </div>
    </button>`;
  }).join('');
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.remove('hidden');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.add('hidden'), 3200);
}

function selectFirstVisibleFallback(previousId) {
  const rows = filtered();
  if (rows.some(inv => inv.id === previousId)) {
    selectInvoice(previousId);
    return;
  }
  if (rows.length) {
    selectInvoice(rows[0].id);
    return;
  }
  selectedId = null;
  els.form.classList.add('hidden');
  els.empty.classList.remove('hidden');
  renderList();
}

function selectInvoice(id) {
  selectedId = Number(id);
  const inv = invoices.find(item => item.id === selectedId);
  if (!inv) return;
  els.empty.classList.add('hidden');
  els.form.classList.remove('hidden');
  els.title.textContent = inv.subject || 'Arve';
  els.statusPill.textContent = statusLabel(inv.status);
  els.statusPill.className = `pill ${inv.status}`;
  els.seen.textContent = `Leitud ${inv.seen_count || 1}x · viimati ${inv.last_seen_at || ''}`;
  for (const field of ['invoice_number', 'invoice_date', 'issuer_name', 'issuer_email', 'invoice_kind', 'amount_total', 'vat_amount', 'due_date', 'issuer_reg_code', 'issuer_vat_no', 'currency', 'payment_details', 'review_note']) {
    els.form.elements[field].value = inv[field] || '';
  }
  els.metaSubject.textContent = inv.subject || '';
  els.metaAttachments.textContent = inv.attachment_names || '';
  els.metaPaths.textContent = inv.attachment_paths || 'Puudub. Tee uus skänn lülitiga -SaveCandidateAttachments.';
  els.metaExtraction.textContent = `${inv.extraction_status || 'not_started'} ${inv.extraction_note || ''}`;
  els.metaPayment.textContent = `${paymentLabel(inv.payment_status)}${inv.paid_date ? ' · ' + inv.paid_date : ''}${inv.paid_amount ? ' · ' + inv.paid_amount + ' ' + (inv.currency || 'EUR') : ''}${inv.bank_match_note ? ' · ' + inv.bank_match_note : ''}`;
  els.metaSource.textContent = `${inv.import_source === 'manual_upload' ? 'Käsitsi üles laaditud' : 'Mail/PST skänn'}${inv.source_folder ? ' · ' + inv.source_folder : ''}`;
  renderList();
}

async function uploadManualInvoice(event) {
  event.preventDefault();
  const file = els.uploadPane.elements.invoice_file.files[0];
  if (!file) {
    els.uploadStatus.textContent = 'Vali kõigepealt fail.';
    return;
  }
  els.uploadStatus.textContent = 'Laen faili üles...';
  const formData = new FormData(els.uploadPane);
  const res = await fetch('/api/manual-upload', { method: 'POST', body: formData });
  const payload = await res.json();
  if (payload.error) {
    els.uploadStatus.textContent = payload.error;
    return;
  }
  els.uploadStatus.textContent = `Lisatud arveregistrisse: ${payload.invoice.subject || payload.invoice.attachment_names}`;
  els.uploadPane.reset();
  await load();
  els.viewMode.value = 'mail';
  renderCurrentView();
  selectInvoice(payload.invoice.id);
}

async function uploadBankStatement(event) {
  event.preventDefault();
  const file = els.bankUploadPane.elements.bank_statement_file.files[0];
  if (!file) {
    els.bankUploadStatus.textContent = 'Vali kõigepealt panga XML fail.';
    return;
  }
  els.bankUploadStatus.textContent = 'Impordin panga väljavõtet...';
  const formData = new FormData(els.bankUploadPane);
  const res = await fetch('/api/bank-upload', { method: 'POST', body: formData });
  const payload = await res.json();
  if (payload.error) {
    els.bankUploadStatus.textContent = payload.error;
    return;
  }
  const db = payload.database || {};
  const rec = payload.reconcile || {};
  els.bankUploadStatus.textContent = [
    `Failis ${payload.summary?.entries || 0} kannet`,
    `uusi ${db.inserted_rows || 0}`,
    `varem olemas ${db.existing_rows || 0}`,
    `pangaga sobitatud arveid ${rec.matched || 0}`
  ].join(' · ');
  els.bankUploadPane.reset();
  await load();
  els.viewMode.value = 'combined';
  renderCurrentView();
}

async function sendBankPaidToMerit() {
  setViewMode('merit-payments');
  await loadMeritPaymentCandidates();
}

function renderMeritPaymentCandidates() {
  const rows = meritPaymentCandidates;
  if (!rows.length) {
    els.meritPaymentsTable.innerHTML = '';
    els.meritPaymentsStatus.textContent = 'Ei leidnud arveid, mida peaks Meritis makstuks märkima.';
    return;
  }
  const selectableCount = rows.filter(item => item.selectable !== false).length;
  els.meritPaymentsStatus.textContent = `Leitud ${rows.length} pangas makstud arvet, neist ${selectableCount} saatmiseks sobivad. Eemalda linnuke nendelt, mida ei soovi Meritisse saata.`;
  els.meritPaymentsTable.innerHTML = `<table class="dataTable">
    <thead>
      <tr><th></th><th>Panga kuupäev</th><th>Meriti kuupäev</th><th>Tarnija</th><th>Arve nr</th><th>Arve summa</th><th>Panga summa</th><th>Kontroll</th><th>Panga vaste</th></tr>
    </thead>
    <tbody>${rows.map(item => `<tr>
      <td><input type="checkbox" class="meritPaymentCheck" value="${escapeHtml(item.candidate_id || item.invoice_id)}" data-default-checked="${item.default_checked === false ? 'false' : 'true'}" ${item.selectable === false ? 'disabled' : ''} ${item.selectable !== false && item.default_checked !== false ? 'checked' : ''}></td>
      <td class="nowrap">${escapeHtml(item.paid_date || '')}</td>
      <td class="nowrap">${escapeHtml(item.payment_date_for_merit || item.paid_date || '')}<div class="muted">${escapeHtml(item.payment_date_note || '')}</div></td>
      <td>${escapeHtml(item.supplier || '')}</td>
      <td class="nowrap">${escapeHtml(item.invoice_number || '')}</td>
      <td class="nowrap">${escapeHtml(item.invoice_amount || item.amount || '')} ${escapeHtml(item.currency || 'EUR')}</td>
      <td class="nowrap">${escapeHtml(item.bank_amount || item.amount || '')} ${escapeHtml(item.currency || 'EUR')}</td>
      <td>${escapeHtml(item.warning || 'OK')}</td>
      <td>${escapeHtml(item.bank_match_note || '')}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function renderMeritPaymentLog(rows) {
  if (!rows?.length) {
    els.meritPaymentsLog.innerHTML = '';
    return;
  }
  els.meritPaymentsLog.innerHTML = `<table class="dataTable">
    <thead>
      <tr><th>#</th><th>Otsus</th><th>Kuupäev</th><th>Tarnija</th><th>Arve nr</th><th>Arve summa</th><th>Panga summa</th><th>Selgitus</th></tr>
    </thead>
    <tbody>${rows.map((row, index) => `<tr>
      <td class="nowrap">${index + 1}</td>
      <td>${escapeHtml(row.result || '')}</td>
      <td class="nowrap">${escapeHtml(row.paid_date || row.invoice_date || '')}</td>
      <td>${escapeHtml(row.supplier || '')}</td>
      <td class="nowrap">${escapeHtml(row.invoice_number || '')}</td>
      <td class="nowrap">${escapeHtml(row.invoice_amount || '')} ${escapeHtml(row.currency || 'EUR')}</td>
      <td class="nowrap">${escapeHtml(row.bank_amount || '')} ${escapeHtml(row.currency || 'EUR')}</td>
      <td>${escapeHtml(row.reason || '')}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function renderMeritPaymentLog(rows) {
  if (!rows?.length) {
    els.meritPaymentsLog.innerHTML = '';
    return;
  }
  els.meritPaymentsLog.innerHTML = `<table class="dataTable">
    <thead>
      <tr><th>#</th><th>Kuupäev</th><th>Tarnija</th><th>Arve nr</th><th>Arve summa</th><th>Kohalik pank</th><th>Kohalik Merit</th><th>Meriti live</th><th>Result</th><th>Selgitus</th></tr>
    </thead>
    <tbody>${rows.map((row, index) => `<tr>
      <td class="nowrap">${index + 1}</td>
      <td class="nowrap">${escapeHtml(row.paid_date || row.invoice_date || '')}</td>
      <td>${escapeHtml(row.supplier || '')}</td>
      <td class="nowrap">${escapeHtml(row.invoice_number || '')}</td>
      <td class="nowrap">${escapeHtml(row.invoice_amount || '')} ${escapeHtml(row.currency || 'EUR')}</td>
      <td>${escapeHtml(row.local_bank_status || ((row.bank_amount || '') + ' ' + (row.currency || 'EUR')))}</td>
      <td>${escapeHtml(row.local_merit_status || '')}</td>
      <td>${escapeHtml(row.live_merit_status || '')}</td>
      <td>${escapeHtml(row.result || '')}</td>
      <td>${escapeHtml(row.reason || '')}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

async function loadMeritPaymentCandidates() {
  els.meritPaymentsStatus.textContent = 'Loen kohaliku andmebaasi arveid...';
  els.meritPaymentsLog.innerHTML = '';
  els.meritPaymentsTable.innerHTML = '';
  const { payload: preview } = await fetchJsonWithProgress(`/api/merit/payment-preview?${periodQuery(els.meritPaymentsPeriod)}`, els.meritPaymentsStatus, [
    'Loen kohalikku arveregistrit...',
    'Filtreerin valitud perioodi pangas makstud arved...',
    'Võrdlen arvenumbreid, summasid ja tarnijaid...',
    'Eemaldan juba makstuks märgitud arved...'
  ], { secondsPerStep: 2, maxBeforeDone: 50, timeoutMs: 15000 });
  if (preview.error) {
    return;
  }
  if (isProjectMissing) {
    els.count.textContent = 'Projektita Meriti arved';
    renderStats({});
    els.form.classList.add('hidden');
    els.meritPreview.classList.add('hidden');
    els.empty.classList.remove('hidden');
    if (!projectMissingRows.length) loadProjectMissing();
    return;
  }
  if (isBankMerit) {
    els.count.textContent = 'Panga maksed vs Meriti arved';
    renderStats({});
    els.form.classList.add('hidden');
    els.meritPreview.classList.add('hidden');
    els.empty.classList.remove('hidden');
    if (!bankMeritRows.length) loadBankMeritCheck();
    return;
  }
  meritPaymentCandidates = preview.payments || [];
  renderMeritPaymentLog(preview.check_log || []);
  renderMeritPaymentCandidates();
  const selectableCount = meritPaymentCandidates.filter(item => item.selectable !== false).length;
  els.meritPaymentsStatus.textContent = `Kontroll valmis (${preview.period_label || 'valitud periood'}). Andmebaasis vaadatud ${preview.checked || 0} arvet. Leitud ${meritPaymentCandidates.length} kandidaati, neist ${selectableCount} saatmiseks sobivad.`;
  if (preview.warning) {
    els.meritPaymentsStatus.innerHTML += `<div class="muted">${escapeHtml(preview.warning)}</div>`;
  }
}

async function loadMeritPaymentCandidates() {
  els.meritPaymentsStatus.textContent = 'Alustan kohalikku kontrolli...';
  els.meritPaymentsLog.innerHTML = '';
  els.meritPaymentsTable.innerHTML = '';
  meritPaymentCandidates = [];
  const logRows = [];
  const streamUrl = `/api/merit/payment-preview-stream?${periodQuery(els.meritPaymentsPeriod)}`;
  await new Promise(resolve => {
    const source = new EventSource(streamUrl);
    source.onmessage = event => {
      const message = JSON.parse(event.data || '{}');
      if (message.type === 'start') {
        els.meritPaymentsStatus.textContent = `Kohalik kandidaatide arv ${message.local_candidates || 0}, perioodist väljas ${message.skipped || 0}. Kontrollin ridu...`;
      } else if (message.type === 'log') {
        const row = message.row || {};
        const existingIndex = logRows.findIndex(item => item.invoice_id && item.invoice_id === row.invoice_id);
        if (existingIndex >= 0 && row.result !== 'Kontrollin') {
          logRows[existingIndex] = row;
        } else if (!(existingIndex >= 0 && row.result === 'Kontrollin')) {
          logRows.push(row);
        }
        renderMeritPaymentLog(logRows);
        els.meritPaymentsStatus.textContent = `Kontrollitud ${message.checked || logRows.length} rida. Viimane: ${row.invoice_number || ''} ${row.supplier || ''} -> ${row.result || ''}`;
      } else if (message.type === 'done') {
        meritPaymentCandidates = message.payments || [];
        renderMeritPaymentCandidates();
        const selectableCount = meritPaymentCandidates.filter(item => item.selectable !== false).length;
        els.meritPaymentsStatus.textContent = `Kontroll valmis (${message.period_label || 'valitud periood'}). Kontrollitud ${message.checked || logRows.length} rida. Leitud ${meritPaymentCandidates.length} kandidaati, neist ${selectableCount} saatmiseks sobivad.`;
        source.close();
        resolve();
      } else if (message.type === 'error') {
        els.meritPaymentsStatus.textContent = message.error || 'Kontroll ebaõnnestus.';
        source.close();
        resolve();
      }
    };
    source.onerror = () => {
      els.meritPaymentsStatus.textContent = 'Live kontrolli ühendus katkes.';
      source.close();
      resolve();
    };
  });
}

async function sendSelectedMeritPayments() {
  const ids = Array.from(els.meritPaymentsTable.querySelectorAll('.meritPaymentCheck:checked'))
    .map(input => input.value)
    .filter(Boolean);
  if (!ids.length) {
    els.meritPaymentsStatus.textContent = 'Vali vähemalt üks arve, mida Meritisse makstuks märkida.';
    return;
  }
  if (!window.confirm(`Saadan Meritisse makstuks märkimise ${ids.length} valitud arvele. Kas jätkan?`)) {
    els.meritPaymentsStatus.textContent = 'Meriti maksete saatmine katkestati.';
    return;
  }
  const progress = startProgress(els.meritPaymentsStatus, [
    `Valmistun saatma ${ids.length} makset Meritisse...`,
    'Otsin Meriti pangakontot...',
    'Saadan maksekandeid Meritisse...',
    'Salvestan tulemused andmebaasi...'
  ], { secondsPerStep: Math.max(4, Math.ceil(ids.length / 8)), maxBeforeDone: 95 });
  const sendRes = await fetch('/api/merit/send-payments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ invoice_ids: ids, period: els.meritPaymentsPeriod.value || 'current' })
  });
  const payload = await sendRes.json();
  if (payload.errors?.length) {
    progress.done(`Saadetud ${payload.sent?.length || 0}, vigu ${payload.errors.length}. Esimene viga: ${payload.errors[0].error}`);
  } else if (payload.error) {
    progress.fail(payload.error);
  } else {
    els.meritPaymentsStatus.textContent = `Meritis makstuks märgitud: ${payload.sent?.length || 0} arvet.`;
  }
  await load();
  await loadMeritPaymentCandidates();
}

function renderProjectMissing() {
  const rows = projectMissingRows;
  if (!rows.length) {
    els.projectMissingTable.innerHTML = '';
    return;
  }
  els.projectMissingTable.innerHTML = `<table class="dataTable">
    <thead>
      <tr><th>Kuupäev</th><th>Tarnija</th><th>Arve nr</th><th>Summa</th><th>Makstud</th><th>Kanne</th><th>Projektiväli</th></tr>
    </thead>
    <tbody>${rows.map(row => `<tr>
      <td class="nowrap">${escapeHtml((row.document_date || '').slice(0, 10))}</td>
      <td>${escapeHtml(row.vendor_name || '')}</td>
      <td class="nowrap">${escapeHtml(row.bill_no || '')}</td>
      <td class="nowrap">${escapeHtml(row.total_sum || '')} ${escapeHtml(row.currency || 'EUR')}</td>
      <td>${escapeHtml(row.paid ? 'jah' : 'ei')}</td>
      <td>${escapeHtml(row.batch_info || '')}</td>
      <td>${escapeHtml(row.project_field || '')}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

async function loadProjectMissing() {
  els.projectMissingTable.innerHTML = '';
  const { payload, progress } = await fetchJsonWithProgress('/api/merit/project-missing', els.projectMissingStatus, [
    'Laen Meriti dimensioone...',
    'Tuvastan projekti välja...',
    'Laen Meriti ostuarveid...',
    'Kontrollin projektivälju ridade kaupa...'
  ], { secondsPerStep: 8, maxBeforeDone: 94 });
  if (payload.error) {
    projectMissingRows = [];
    return;
  }
  projectMissingRows = payload.rows || [];
  els.projectMissingStatus.textContent = `Kontrollitud ${payload.checked || 0} ostuarvet perioodil ${payload.period_start || ''} kuni ${payload.period_end || ''}. Projektita: ${projectMissingRows.length}. Kontrollitud väli: ${payload.project_field || ''}.`;
  renderProjectMissing();
}

function bankMeritStatusText(status) {
  return {
    ok_paid: 'OK: pangas ja Meritis makstud',
    bank_paid_merit_unpaid: 'Pangas makstud, Meritis maksmata',
    merit_paid_no_bank_match: 'Meritis makstud, pangavaste puudub',
    unpaid_no_bank_match: 'Meritis maksmata, pangavaste puudub',
    bank_debit_no_merit: 'Pangakanne, Meriti arvet ei leitud'
  }[status] || status || '';
}

function renderBankMeritCheck() {
  const rows = bankMeritRows;
  if (!rows.length) {
    els.bankMeritTable.innerHTML = '';
    return;
  }
  els.bankMeritTable.innerHTML = `<table class="dataTable">
    <thead>
      <tr><th>Staatus</th><th>Kuupäev</th><th>Tarnija</th><th>Arve nr</th><th>Meriti summa</th><th>Meriti makse</th><th>Panga kuupäev</th><th>Panga summa</th><th>Panga selgitus</th><th>Skoor</th></tr>
    </thead>
    <tbody>${rows.map(row => `<tr>
      <td>${escapeHtml(bankMeritStatusText(row.status))}</td>
      <td class="nowrap">${escapeHtml((row.merit_invoice_date || row.bank_date || '').slice(0, 10))}</td>
      <td>${escapeHtml(row.supplier || row.bank_party || '')}</td>
      <td class="nowrap">${escapeHtml(row.invoice_number || '')}</td>
      <td class="nowrap">${escapeHtml(row.merit_amount || '')} ${escapeHtml(row.currency || 'EUR')}</td>
      <td>${escapeHtml(paymentText(row.merit_payment_status))}</td>
      <td class="nowrap">${escapeHtml((row.bank_date || '').slice(0, 10))}</td>
      <td class="nowrap">${escapeHtml(row.bank_amount || '')} ${escapeHtml(row.bank_currency || row.currency || 'EUR')}</td>
      <td>${escapeHtml(row.bank_remittance || '')}</td>
      <td>${escapeHtml(String(row.bank_score || ''))}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

async function loadBankMeritCheck() {
  els.bankMeritTable.innerHTML = '';
  const { payload, progress } = await fetchJsonWithProgress(`/api/merit/bank-check?${periodQuery(els.bankMeritPeriod)}`, els.bankMeritStatus, [
    'Laen Meriti ostuarveid kvartalite kaupa...',
    'Loen pangaandmebaasi kandeid...',
    'Võrdlen arveid pangamaksetega...',
    'Koostan erandite nimekirja...'
  ], { secondsPerStep: 12, maxBeforeDone: 96 });
  if (payload.error) {
    bankMeritRows = [];
    return;
  }
  bankMeritRows = payload.rows || [];
  const summary = payload.summary || {};
  progress.done(`Kontrollitud ${payload.period_label || 'valitud periood'}: ${payload.merit_count || 0} Meriti arvet ja ${payload.bank_count || 0} pangakannet. OK ${summary.ok_paid || 0}, pangas makstud aga Meritis maksmata ${summary.bank_paid_merit_unpaid || 0}, pangakanne ilma Meriti arveta ${summary.bank_debit_no_merit || 0}.`);
  renderBankMeritCheck();
}

function formData() {
  const data = {};
  for (const field of ['invoice_number', 'invoice_date', 'issuer_name', 'issuer_email', 'invoice_kind', 'amount_total', 'vat_amount', 'due_date', 'issuer_reg_code', 'issuer_vat_no', 'currency', 'payment_details', 'review_note']) {
    data[field] = els.form.elements[field].value;
  }
  return data;
}

async function extractSelected() {
  if (!selectedId) return;
  const inv = invoices.find(item => item.id === selectedId);
  if (!inv?.attachment_paths) {
    els.metaExtraction.textContent = 'PDF/XML faili ei ole salvestatud. Tee uus skänn lülitiga -SaveCandidateAttachments.';
    alert('Selle arve PDF/XML faili ei ole salvestatud. Tee uus skänn lülitiga -SaveCandidateAttachments ja ava siis uus skännitulemus.');
    return;
  }
  const res = await fetch(`/api/invoices/${selectedId}/extract`, { method: 'POST' });
  const payload = await res.json();
  if (payload.message) {
    els.metaExtraction.textContent = payload.message;
    showToast(payload.message);
  }
  await load();
  selectInvoice(selectedId);
}

async function showMeritPreview(invoiceId) {
  const res = await fetch(`/api/invoices/${invoiceId}/merit-preview`);
  const payload = await res.json();
  if (payload.error) {
    showToast(payload.error);
    return;
  }
  selectedId = Number(invoiceId);
  els.form.classList.add('hidden');
  els.empty.classList.add('hidden');
  els.meritPreview.classList.remove('hidden');
  els.meritSendStatus.classList.add('hidden');
  renderMeritHuman(payload.human_summary || {});
  const warnings = payload.warnings || [];
  els.meritWarnings.innerHTML = warnings.length
    ? warnings.map(item => `<div>${escapeHtml(item)}</div>`).join('')
    : '<div>Eelvaade on valmis. Päris saatmist veel ei tehta.</div>';
  els.meritJson.textContent = JSON.stringify(payload, null, 2);
}

async function sendSelectedToMerit(force = false) {
  if (!selectedId) return;
  const message = force
    ? 'See arve on juba varem Meritisse saadetud. Kas soovid selle siiski uuesti saata? Kontrolli Meritis enne, et topeltarvet ei tekiks.'
    : 'Kas oled kindel, et soovid selle ostuarve päriselt Meritisse saata?';
  if (!window.confirm(message)) return;
  els.meritSendStatus.classList.remove('hidden');
  els.meritSendStatus.textContent = force ? 'Saadan arvet uuesti Meritisse...' : 'Saadan arvet Meritisse...';
  const suffix = force ? '?force=true' : '';
  const res = await fetch(`/api/invoices/${selectedId}/send-merit${suffix}`, { method: 'POST' });
  const payload = await res.json();
  if (payload.ok) {
    const payment = payload.auto_payment || {};
    const paymentText = payment.sent && payment.sent.length
      ? ' Pangas tuvastatud makse märgiti samuti Meritisse.'
      : payment.skipped
        ? ` Makse märkimist ei tehtud: ${payment.reason || 'pangas makset ei tuvastatud'}.`
        : payment.error
          ? ` Makse märkimine ebaõnnestus: ${payment.error}.`
          : '';
    els.meritSendStatus.textContent = (force ? 'Arve saadeti uuesti Meritisse.' : 'Arve saadeti Meritisse.') + paymentText + ' Vastus on JSON eelvaates all.';
    els.meritJson.textContent = JSON.stringify(payload, null, 2);
    showToast((force ? 'Arve saadeti uuesti Meritisse.' : 'Arve saadeti Meritisse.') + (payment.sent && payment.sent.length ? ' Makse märgiti ka makstuks.' : ''));
    await load();
  } else {
    els.meritSendStatus.textContent = `Meritisse saatmine ebaõnnestus: ${payload.error || 'tundmatu viga'}`;
    els.meritJson.textContent = JSON.stringify(payload, null, 2);
  }
}

async function createPaymentFile() {
  if (!selectedId) return;
  const inv = invoices.find(item => item.id === selectedId);
  if (!window.confirm('Koostan sellest arvest Swedbanki imporditava SEPA XML maksefaili. Makse kinnitamine jääb pangas PIN-koodiga.')) return;
  await fetch(`/api/invoices/${selectedId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: inv?.status || 'pending', fields: formData(), note: formData().review_note || '' })
  });
  const res = await fetch(`/api/invoices/${selectedId}/payment-file`, { method: 'POST' });
  const payload = await res.json();
  if (!payload.ok) {
    showToast(`Maksefaili ei koostatud: ${payload.error || 'tundmatu viga'}`);
    return;
  }
  const blob = new Blob([payload.xml], { type: 'application/xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = payload.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast(`Maksefail valmis: ${payload.filename}`);
  await load();
  selectInvoice(selectedId);
}

function humanRow(label, value) {
  return `<div class="humanRow"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value || '-')}</span></div>`;
}

function humanGroup(title, rows) {
  return `<section class="humanGroup"><h3>${escapeHtml(title)}</h3><div class="humanRows">${rows.join('')}</div></section>`;
}

function renderMeritHuman(summary) {
  els.meritHuman.innerHTML = [
    humanGroup('Tarnija', [
      humanRow('Nimi', summary.vendor_name),
      humanRow('Registrikood', summary.vendor_reg_no),
      humanRow('KMKR', summary.vendor_vat_no),
      humanRow('Pangarekvisiit', summary.bank_account)
    ]),
    humanGroup('Arve', [
      humanRow('Arve nr', summary.invoice_number),
      humanRow('Arve kuupäev', summary.invoice_date),
      humanRow('Maksetähtaeg', summary.due_date),
      humanRow('Kande kuupäev', summary.transaction_date)
    ]),
    humanGroup('Summad', [
      humanRow('Neto', `${summary.net_amount || 0} ${summary.currency || 'EUR'}`),
      humanRow('KM', `${summary.vat_amount || 0} ${summary.currency || 'EUR'}`),
      humanRow('Bruto', `${summary.gross_amount || 0} ${summary.currency || 'EUR'}`),
      humanRow('KM TaxId', summary.tax_id)
    ]),
    humanGroup('Makse ja manus', [
      humanRow('Makse staatus', summary.payment_status),
      humanRow('Makstud summa', summary.paid_amount ? `${summary.paid_amount} ${summary.currency || 'EUR'}` : ''),
      humanRow('Makse kuupäev', summary.paid_date),
      humanRow('Makseviis', summary.payment_method),
      humanRow('Kuluartikkel', summary.item_code),
      humanRow('Konto', summary.gl_account_code),
      humanRow('Rea kirjeldus', summary.item_description),
      humanRow('Projektiridu', summary.project_rows_count || 0),
      humanRow('Projektid', summary.project_codes || ''),
      humanRow('PDF manus', summary.attachment_included ? summary.attachment_filename : 'puudub')
    ])
  ].join('');
}

async function saveStatus(status) {
  if (!selectedId) return;
  const previousId = selectedId;
  await fetch(`/api/invoices/${selectedId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, fields: formData(), note: formData().review_note || '' })
  });
  await load();
  selectFirstVisibleFallback(previousId);
  showToast(status === 'confirmed' ? 'Arve kinnitatud. Kui filter on Ootel, liigub see rida nimekirjast ära.' : 'Arve staatus salvestatud.');
}

async function load() {
  const [invoiceRes, reconciliationRes] = await Promise.all([
    fetch('/api/invoices'),
    fetch('/api/reconciliation')
  ]);
  const data = await invoiceRes.json();
  const reconciliationData = await reconciliationRes.json();
  invoices = data.invoices;
  currentCounts = data.counts;
  reconciliation = reconciliationData;
  renderCurrentView();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[ch]));
}

els.list.addEventListener('click', event => {
  const row = event.target.closest('.row');
  if (row) selectInvoice(row.dataset.id);
});
els.reconciliationTable.addEventListener('change', event => {
  const control = event.target.closest('[data-filter]');
  if (!control) return;
  columnFilters[control.dataset.filter] = control.value;
  renderCurrentView();
});
els.reconciliationTable.addEventListener('keydown', event => {
  const control = event.target.closest('input[data-filter]');
  if (!control || event.key !== 'Enter') return;
  event.preventDefault();
  columnFilters[control.dataset.filter] = control.value;
  renderCurrentView();
});
els.reconciliationTable.addEventListener('click', event => {
  const meritButton = event.target.closest('.meritRowBtn');
  if (meritButton) {
    showMeritPreview(meritButton.dataset.invoiceId);
    return;
  }
  const openButton = event.target.closest('.openInvoiceBtn');
  if (openButton) {
    selectInvoice(openButton.dataset.invoiceId);
    return;
  }
  if (event.target.closest('[data-filter]')) return;
  const row = event.target.closest('tr[data-invoice-id]');
  if (row) selectInvoice(row.dataset.invoiceId);
});
els.viewButtons.addEventListener('click', event => {
  const button = event.target.closest('[data-view]');
  if (button) setViewMode(button.dataset.view);
});
els.viewMode.addEventListener('change', renderCurrentView);
els.status.addEventListener('change', renderList);
els.kind.addEventListener('change', renderList);
els.search.addEventListener('input', renderCurrentView);
els.hideDuplicates.addEventListener('change', renderCurrentView);
document.getElementById('refreshBtn').addEventListener('click', load);
document.getElementById('testMeritBtn').addEventListener('click', testMeritConnection);
document.getElementById('sendMeritPaymentsBtn').addEventListener('click', sendBankPaidToMerit);
document.getElementById('selectAllMeritPaymentsBtn').addEventListener('click', () => {
  els.meritPaymentsTable.querySelectorAll('.meritPaymentCheck:not(:disabled)').forEach(input => { input.checked = input.dataset.defaultChecked !== 'false'; });
});
document.getElementById('clearMeritPaymentsBtn').addEventListener('click', () => {
  els.meritPaymentsTable.querySelectorAll('.meritPaymentCheck').forEach(input => { input.checked = false; });
});
document.getElementById('sendSelectedMeritPaymentsBtn').addEventListener('click', sendSelectedMeritPayments);
document.getElementById('loadProjectMissingBtn').addEventListener('click', loadProjectMissing);
document.getElementById('loadBankMeritBtn').addEventListener('click', loadBankMeritCheck);
els.meritPaymentsPeriod.addEventListener('change', () => {
  meritPaymentCandidates = [];
  if (els.viewMode.value === 'merit-payments') loadMeritPaymentCandidates();
});
els.bankMeritPeriod.addEventListener('change', () => {
  bankMeritRows = [];
  if (els.viewMode.value === 'bank-merit-check') loadBankMeritCheck();
});
els.uploadPane.addEventListener('submit', uploadManualInvoice);
els.bankUploadPane.addEventListener('submit', uploadBankStatement);
els.settingsPane.addEventListener('submit', event => {
  event.preventDefault();
  saveSettings();
});
document.getElementById('confirmBtn').addEventListener('click', () => saveStatus('confirmed'));
document.getElementById('rejectBtn').addEventListener('click', () => saveStatus('rejected'));
document.getElementById('pendingBtn').addEventListener('click', () => saveStatus('pending'));
document.getElementById('extractBtn').addEventListener('click', extractSelected);
document.getElementById('meritPreviewBtn').addEventListener('click', () => {
  if (selectedId) showMeritPreview(selectedId);
});
document.getElementById('sendMeritBtn').addEventListener('click', () => sendSelectedToMerit(false));
document.getElementById('resendMeritBtn').addEventListener('click', () => sendSelectedToMerit(true));
document.getElementById('paymentFileBtn').addEventListener('click', createPaymentFile);
els.form.addEventListener('submit', event => {
  event.preventDefault();
  const inv = invoices.find(item => item.id === selectedId);
  saveStatus(inv?.status || 'pending');
});

load();
"""


def row_to_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def money(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def paid_label_from_bank(row: dict[str, str]) -> str:
    if row.get("bank_date"):
        return "paid"
    if row.get("payment_status"):
        return row.get("payment_status", "")
    return "no_bank_match"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value or "arve.pdf").strip(" ._")
    return cleaned or "arve.pdf"


def parse_content_disposition(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if "=" in part:
            key, raw = part.split("=", 1)
            result[key.strip().lower()] = raw.strip().strip('"')
    return result


def parse_multipart_form(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("Multipart boundary puudub.")
    boundary = match.group("boundary").strip().strip('"').encode("utf-8")
    fields: dict[str, str] = {}
    files: dict[str, dict[str, object]] = {}

    for raw_part in body.split(b"--" + boundary):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers: dict[str, str] = {}
        for line in header_blob.decode("utf-8", errors="replace").split("\r\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        disposition = parse_content_disposition(headers.get("content-disposition", ""))
        name = disposition.get("name", "")
        filename = disposition.get("filename", "")
        content = content.rstrip(b"\r\n")
        if filename:
            files[name] = {
                "filename": safe_filename(filename),
                "content": content,
                "content_type": headers.get("content-type", "application/octet-stream"),
            }
        elif name:
            fields[name] = content.decode("utf-8", errors="replace").strip()
    return fields, files


MERIT_SETTING_KEYS = [
    "payment_debtor_name",
    "payment_debtor_iban",
    "merit_api_id",
    "merit_api_key",
    "merit_default_tax_pct",
    "merit_default_item_code",
    "merit_default_gl_account_code",
    "merit_payment_method",
    "merit_project_dimension_id",
]


def decimal_value(value: str | None) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def money_amount_matches(first: str | None, second: str | None) -> bool:
    first_amount = decimal_value(first).quantize(Decimal("0.01"))
    second_amount = decimal_value(second).quantize(Decimal("0.01"))
    return first_amount == second_amount


def norm_lookup(value: str | None) -> str:
    return re.sub(r"[^0-9a-zõäöü]+", "", str(value or "").lower())


COMPANY_WORD_STOPLIST = {
    "ab",
    "aktsiaselts",
    "as",
    "fie",
    "gmbh",
    "inc",
    "llc",
    "ltd",
    "mtu",
    "osauehing",
    "osauhing",
    "ou",
    "oy",
    "sa",
}


def company_name_tokens(value: str | None) -> set[str]:
    words = re.findall(r"[0-9a-z]+", str(value or "").lower())
    return {word for word in words if len(word) > 1 and word not in COMPANY_WORD_STOPLIST}


def company_names_match(first: str | None, second: str | None) -> bool:
    first_tokens = company_name_tokens(first)
    second_tokens = company_name_tokens(second)
    if not first_tokens or not second_tokens:
        return False
    overlap = first_tokens & second_tokens
    if first_tokens <= second_tokens or second_tokens <= first_tokens:
        return True
    return len(overlap) >= min(2, len(first_tokens), len(second_tokens))


def money_lookup(value: str | None) -> Decimal:
    return decimal_value(value).quantize(Decimal("0.01"))


def yyyymmdd(value: str | None) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) >= 8:
        return digits[:8]
    return ""


def parse_iso_day(value: str | None) -> datetime | None:
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def quarter_periods(start_year: int, end: datetime) -> list[tuple[str, str]]:
    periods: list[tuple[str, str]] = []
    for year in range(start_year, end.year + 1):
        for start_month, end_month, end_day in ((1, 3, 31), (4, 6, 30), (7, 9, 30), (10, 12, 31)):
            start = datetime(year, start_month, 1)
            period_end = datetime(year, end_month, end_day)
            if start > end:
                continue
            if period_end > end:
                period_end = end
            periods.append((start.strftime("%Y%m%d"), period_end.strftime("%Y%m%d")))
    return periods


def add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return datetime(year, month, 1)


def selected_period_range(period: str | None, reference: datetime | None = None) -> tuple[datetime | None, datetime | None, str]:
    key = (period or "current").strip().lower()
    now = reference or datetime.now()
    if key == "all":
        return None, None, "Kogu ajalugu"
    if key == "previous":
        start = add_months(datetime(now.year, now.month, 1), -1)
        end = datetime(now.year, now.month, 1) - timedelta(days=1)
        return start, end, "Eelmine kuu"
    if key == "current":
        start = datetime(now.year, now.month, 1)
        return start, now, "Jooksev kuu"
    if key == "year":
        return datetime(now.year, 1, 1), now, "Jooksev aasta"
    start = add_months(datetime(now.year, now.month, 1), -2)
    return start, now, "Viimased 3 kuud"


def in_selected_period(date_value: str | None, start: datetime | None, end: datetime | None) -> bool:
    parsed = parse_iso_day(date_value)
    if parsed is None:
        return False
    if start and parsed < start:
        return False
    if end and parsed > end:
        return False
    return True


def merit_error_means_no_unpaid_invoice(value: str | None) -> bool:
    text = str(value or "").lower()
    return "puudub selliste parameetritega tasumata ostuarve" in text


def merit_response_vendor_id(value: str | None) -> str:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("VendorId", "") or "")
    return ""


def first_company_name(value: str | None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    match = re.search(r"\b(.+?\b(?:OÜ|OU|AS|MTÜ|SA|FIE))\b", text, re.IGNORECASE)
    if match:
        return match.group(1).strip(" ,.;:-")
    for marker in (" Tel", " tel", " E-post", " e-post", " Email", " email", " info@", " www."):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    return text[:150].strip(" ,.;:-")


def invoice_number_from_bank_remittance(value: str | None) -> str:
    text = str(value or "")
    patterns = (
        r"\barve\s*(?:nr|number|no)?\.?\s*:?\s*([A-Z0-9._/-]{2,})",
        r"\binvoice\s*(?:nr|number|no)?\.?\s*:?\s*([A-Z0-9._/-]{2,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .:-/")
    return ""


def merit_row_total(row: dict) -> str:
    for key in ("TotalSum", "TotalAmount", "Total", "Summa kokku", "amount_total"):
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


def merit_row_paid_amount(row: dict) -> str:
    for key in ("PaidAmount", "paid_amount", "Tasutud summa"):
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


def merit_row_is_paid(row: dict) -> bool:
    paid_value = row.get("Paid")
    if isinstance(paid_value, bool):
        return paid_value
    if str(paid_value).strip().lower() in {"true", "1", "yes", "paid"}:
        return True
    total = money_lookup(merit_row_total(row))
    paid = money_lookup(merit_row_paid_amount(row))
    return bool(total and paid >= total)


def merit_row_signature(row: dict) -> tuple[str, Decimal]:
    return (
        norm_lookup(str(row.get("BillNo") or row.get("invoice_number") or row.get("Arve nr") or "")),
        money_lookup(merit_row_total(row)),
    )


def invoice_merge_key(invoice_number: str | None, amount_value: str | None) -> tuple[str, Decimal]:
    return (norm_lookup(invoice_number), money_lookup(amount_value))


def find_bank_merge_target(bank_row: dict[str, str], combined_rows: list[dict[str, object]]) -> dict[str, object] | None:
    bank_amount = money_lookup(bank_row.get("amount"))
    bank_party = str(bank_row.get("party_name", "") or "")
    bank_remittance = str(bank_row.get("remittance", "") or "")
    bank_text = f"{bank_party} {bank_remittance}"
    if not bank_amount or not bank_text.strip():
        return None

    for item in combined_rows:
        if item.get("source") == "Pank":
            continue
        if money_lookup(str(item.get("amount", "") or "")) != bank_amount:
            continue
        supplier = str(item.get("supplier", "") or "")
        existing_bank_party = str(item.get("bank_party", "") or "")
        if (
            company_names_match(supplier, bank_party)
            or company_names_match(supplier, bank_text)
            or company_names_match(existing_bank_party, bank_party)
        ):
            return item
    return None


def attach_bank_row_to_reconciliation_item(item: dict[str, object], bank_row: dict[str, str]) -> None:
    item["exists_bank"] = True
    if str(item.get("bank_payment_status", "") or "") in {"", "unknown", "unmatched", "no_bank_match", "bank_debit_no_merit"}:
        item["bank_payment_status"] = "paid"
    if not item.get("bank_date"):
        item["bank_date"] = bank_row.get("booking_date", "")
    if not item.get("bank_amount"):
        item["bank_amount"] = money(bank_row.get("amount"))
    if not item.get("bank_party"):
        item["bank_party"] = bank_row.get("party_name", "")
    bank_note = bank_row.get("remittance", "")
    if bank_note and bank_note not in str(item.get("bank_remittance", "") or ""):
        item["bank_remittance"] = bank_note


def bank_debit_rows_for_reconciliation(connection) -> list[dict[str, str]]:
    return [
        row
        for row in list_bank_transactions(connection)
        if str(row.get("credit_debit", "") or "").upper() == "DBIT"
        and str(row.get("amount", "") or "").strip()
    ]


def merit_payment_status_from_row(row: dict) -> str:
    total = money_lookup(merit_row_total(row))
    paid = money_lookup(merit_row_paid_amount(row))
    if merit_row_is_paid(row):
        return "paid"
    if paid > 0 and paid < total:
        return "partially_paid"
    return "unpaid"


def normalize_merit_purchase_row(row: dict) -> dict[str, str]:
    return {
        "invoice_date": str(row.get("DocumentDate", "") or "")[:10],
        "supplier": str(row.get("VendorName", "") or ""),
        "invoice_number": str(row.get("BillNo", "") or ""),
        "amount_total": merit_row_total(row),
        "paid_amount": merit_row_paid_amount(row),
        "payment_status": merit_payment_status_from_row(row),
        "currency": str(row.get("CurrencyCode", "") or "EUR"),
        "description": " ".join(str(row.get(key, "") or "") for key in ("BatchInfo", "ReferenceNo", "Dimension1Code", "Dimension2Code")),
        "pih_id": str(row.get("PIHId", "") or ""),
    }


def find_matching_merit_row_for_payment(item: dict[str, object], merit_rows: list[dict]) -> dict | None:
    invoice_number = norm_lookup(str(item.get("invoice_number", "") or ""))
    amount_value = money_lookup(str(item.get("invoice_amount") or item.get("amount") or ""))
    supplier = str(item.get("supplier", "") or "")
    matches = []
    for row in merit_rows:
        row_number, row_amount = merit_row_signature(row)
        if invoice_number and row_number != invoice_number:
            continue
        if amount_value and row_amount != amount_value:
            continue
        row_supplier = str(row.get("VendorName", "") or "")
        score = 1 if company_names_match(supplier, row_supplier) else 0
        matches.append((score, row))
    if not matches:
        return None
    matches.sort(key=lambda pair: pair[0], reverse=True)
    return matches[0][1]


def find_tax_id(taxes, tax_pct: str) -> str:
    target = decimal_value(tax_pct)
    if not isinstance(taxes, list):
        return ""
    for tax in taxes:
        if not isinstance(tax, dict):
            continue
        if decimal_value(str(tax.get("TaxPct", ""))) == target:
            return str(tax.get("Id", ""))
    return ""


def redact_attachment(payload: dict) -> dict:
    copy = json.loads(json.dumps(payload, ensure_ascii=False))
    attachment = copy.get("Attachment")
    if isinstance(attachment, dict) and attachment.get("FileContent"):
        attachment["FileContent"] = f"<redacted base64, {len(str(attachment['FileContent']))} chars>"
    return copy


def configured_project_dim_id(settings: dict[str, str]) -> int | None:
    value = str(settings.get("merit_project_dimension_id", "")).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def merit_payment_date(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 8:
        return digits[:8] + "0000"
    return datetime.now().strftime("%Y%m%d0000")


def later_iso_date(first: str, second: str) -> str:
    first_value = (first or "")[:10]
    second_value = (second or "")[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", first_value) and re.match(r"^\d{4}-\d{2}-\d{2}$", second_value):
        return max(first_value, second_value)
    return first_value or second_value


def find_merit_bank(banks, iban: str) -> dict | None:
    target = re.sub(r"\s+", "", iban or "").upper()
    if not isinstance(banks, list):
        return None
    if target:
        for bank in banks:
            bank_iban = re.sub(r"\s+", "", str(bank.get("IBANCode", ""))).upper()
            if bank_iban == target:
                return bank
    for bank in banks:
        if str(bank.get("CurrencyCode", "")).upper() == "EUR":
            return bank
    return banks[0] if banks else None


def resolve_merit_vendor_name(client: MeritClient, item: dict) -> str:
    vendor_id = merit_response_vendor_id(str(item.get("merit_response", "") or ""))
    if vendor_id:
        vendor = client.get_vendors({"Id": vendor_id})
        if isinstance(vendor, dict) and vendor.get("Name"):
            return str(vendor.get("Name", "")).strip()
        if isinstance(vendor, list) and vendor and isinstance(vendor[0], dict) and vendor[0].get("Name"):
            return str(vendor[0].get("Name", "")).strip()
    return first_company_name(str(item.get("supplier", "") or ""))


def find_project_dimension_id(dimensions: list[dict], settings: dict[str, str]) -> int | None:
    configured = configured_project_dim_id(settings)
    if configured:
        return configured
    for item in dimensions:
        name = str(item.get("DimName", "")).lower()
        if "projekt" in name or "project" in name:
            try:
                return int(item.get("DimId"))
            except (TypeError, ValueError):
                return None
    return None


def project_dimension_field(dim_id: int | None) -> str:
    if not dim_id or dim_id < 1 or dim_id > 7:
        return ""
    return f"Dimension{dim_id}Code"


def dimension_values_by_code(dimensions: list[dict], dim_id: int) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in dimensions:
        try:
            item_dim_id = int(item.get("DimId"))
        except (TypeError, ValueError):
            continue
        if item_dim_id != dim_id:
            continue
        code = str(item.get("Code", "")).strip()
        if code:
            result[code] = item
    return result


def ensure_merit_project_values(client: MeritClient, settings: dict[str, str], row) -> tuple[int | None, dict[str, dict], list[str]]:
    project_lines = parse_project_lines_from_attachments(row["attachment_paths"])
    if not project_lines:
        return None, {}, []

    dimensions = client.get_dimensions(all_values=True)
    if not isinstance(dimensions, list):
        raise MeritApiError("Meriti getdimensions vastus ei olnud nimekiri.")
    dim_id = find_project_dimension_id(dimensions, settings)
    if not dim_id:
        raise MeritApiError("Meriti projekti dimensiooni ei leitud. Lisa seadistuses Projekti DimId.")

    values = dimension_values_by_code(dimensions, dim_id)
    unique_lines = {line.project_code: line for line in project_lines}
    missing = [line for code, line in unique_lines.items() if code not in values]
    created_codes: list[str] = []
    if missing:
        client.send_dimension_values(
            [
                {
                    "DimId": dim_id,
                    "DimValueCode": line.project_code,
                    "DimValueName": f"{line.project_code} {line.project_name}"[:64],
                    "EndDate": "",
                }
                for line in missing
            ]
        )
        created_codes = [line.project_code for line in missing]
        dimensions = client.get_dimensions(all_values=True)
        if isinstance(dimensions, list):
            values = dimension_values_by_code(dimensions, dim_id)

    return dim_id, values, created_codes


class InvoiceWebApp:
    def __init__(self, csv_path: Path, db_path: Path):
        self.csv_path = csv_path
        self.db_path = db_path
        self.connection = connect(db_path)
        if csv_path.exists():
            self.import_candidates()
        self.backfill_invoice_kinds()

    def import_candidates(self) -> None:
        rows = read_rows(self.csv_path)
        for row in rows:
            if row.get("is_duplicate", "false") == "true":
                continue
            if row.get("classification", "likely_invoice") not in {"likely_invoice", "possible_invoice", "needs_review"}:
                continue
            data = candidate_to_data(row)
            if get_invoice(self.connection, data["fingerprint"]) is None:
                upsert_seen(self.connection, data)

    def backfill_invoice_kinds(self) -> None:
        self.connection.execute(
            """
            UPDATE invoices
            SET invoice_kind = 'own_sales_invoice'
            WHERE invoice_kind = 'purchase_candidate'
              AND (
                subject LIKE 'Erlin OÜ Arve%'
                OR subject LIKE 'Erlin OU Arve%'
                OR issuer_name IN ('Erlin OÜ', 'Erlin OU')
                OR
                lower(subject) LIKE 'erlin oü arve%'
                OR lower(subject) LIKE 'erlin ou arve%'
                OR lower(issuer_email) IN ('arve@merit.ee', 'noreply@merit.ee')
                OR lower(issuer_name) IN ('erlin oü', 'erlin ou')
              )
            """
        )
        self.connection.commit()

    def list_invoices(self) -> dict:
        rows = self.connection.execute(
            """
            SELECT id, fingerprint, status, invoice_kind, invoice_number, invoice_date, issuer_name,
                   issuer_email, payment_details, amount_total, vat_amount, due_date,
                   issuer_reg_code, issuer_vat_no, currency, subject, attachment_names,
                   attachment_paths, source_folder, import_source, extraction_status, extraction_note,
                   payment_status, paid_amount, paid_date, bank_match_note,
                   merit_status, merit_sent_at, merit_error,
                   first_seen_at, last_seen_at, seen_count, confirmed_at, rejected_at, review_note
            FROM invoices
            ORDER BY
                CASE status WHEN 'pending' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END,
                invoice_date DESC,
                issuer_name
            """
        ).fetchall()
        return {
            "counts": status_counts(self.connection),
            "invoices": [row_to_dict(row) | {"is_duplicate": "false"} for row in rows],
        }

    def merit_settings(self) -> dict:
        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        return {
            "payment_debtor_name": settings.get("payment_debtor_name", "") or "ERLIN OÜ",
            "payment_debtor_iban": settings.get("payment_debtor_iban", ""),
            "merit_api_id": settings.get("merit_api_id", ""),
            "merit_default_tax_pct": settings.get("merit_default_tax_pct", "") or "24",
            "merit_default_item_code": settings.get("merit_default_item_code", "") or DEFAULT_ITEM_CODE,
            "merit_default_gl_account_code": settings.get("merit_default_gl_account_code", "") or DEFAULT_GL_ACCOUNT_CODE,
            "merit_payment_method": settings.get("merit_payment_method", "") or "Pank",
            "merit_project_dimension_id": settings.get("merit_project_dimension_id", ""),
            "has_api_key": bool(settings.get("merit_api_key", "")),
        }

    def save_merit_settings(self, payload: dict) -> dict:
        current = get_settings(self.connection, MERIT_SETTING_KEYS)
        values = {
            "payment_debtor_name": str(payload.get("payment_debtor_name", "ERLIN OÜ")).strip() or "ERLIN OÜ",
            "payment_debtor_iban": str(payload.get("payment_debtor_iban", "")).strip(),
            "merit_api_id": str(payload.get("merit_api_id", "")).strip(),
            "merit_default_tax_pct": str(payload.get("merit_default_tax_pct", "24")).strip() or "24",
            "merit_default_item_code": str(payload.get("merit_default_item_code", DEFAULT_ITEM_CODE)).strip() or DEFAULT_ITEM_CODE,
            "merit_default_gl_account_code": str(payload.get("merit_default_gl_account_code", DEFAULT_GL_ACCOUNT_CODE)).strip() or DEFAULT_GL_ACCOUNT_CODE,
            "merit_payment_method": str(payload.get("merit_payment_method", "Pank")).strip() or "Pank",
            "merit_project_dimension_id": str(payload.get("merit_project_dimension_id", "")).strip(),
        }
        api_key = str(payload.get("merit_api_key", "")).strip()
        values["merit_api_key"] = api_key or current.get("merit_api_key", "")
        set_settings(self.connection, values)
        return {"ok": True, "message": "Meriti seadistus salvestatud.", **self.merit_settings()}

    def test_merit_connection(self) -> dict:
        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        client = MeritClient(settings.get("merit_api_id", ""), settings.get("merit_api_key", ""))
        try:
            taxes = client.get_taxes()
        except MeritApiError as exc:
            return {"ok": False, "error": str(exc)}
        tax_count = len(taxes) if isinstance(taxes, list) else 0
        return {"ok": True, "tax_count": tax_count, "taxes_preview": taxes[:5] if isinstance(taxes, list) else taxes}

    def merit_project_missing(self) -> dict:
        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        client = MeritClient(settings.get("merit_api_id", ""), settings.get("merit_api_key", ""))
        dimensions = client.get_dimensions(all_values=True)
        if not isinstance(dimensions, list):
            return {"ok": False, "error": "Meriti dimensioonide vastus ei olnud nimekiri."}
        dim_id = find_project_dimension_id(dimensions, settings)
        field = project_dimension_field(dim_id)
        if not field:
            return {"ok": False, "error": "Projekti dimensiooni ei leitud. Lisa seadistuses Projekti DimId vahemikus 1-7."}

        today = datetime.now()
        period_start = f"{today.year}0101"
        period_end = today.strftime("%Y%m%d")
        rows = client.get_purchase_invoices(period_start, period_end, unpaid=False)
        if not isinstance(rows, list):
            return {"ok": False, "error": "Meriti ostuarvete vastus ei olnud nimekiri."}

        missing: list[dict[str, object]] = []
        for row in rows:
            project_code = str(row.get(field, "") or "").strip()
            if project_code:
                continue
            missing.append(
                {
                    "document_date": str(row.get("DocumentDate", "") or ""),
                    "vendor_name": str(row.get("VendorName", "") or ""),
                    "bill_no": str(row.get("BillNo", "") or ""),
                    "total_sum": str(row.get("TotalSum", "") or ""),
                    "currency": str(row.get("CurrencyCode", "") or "EUR"),
                    "paid": merit_row_is_paid(row),
                    "paid_amount": str(row.get("PaidAmount", "") or ""),
                    "batch_info": str(row.get("BatchInfo", "") or ""),
                    "project_field": field,
                    "pih_id": str(row.get("PIHId", "") or ""),
                }
            )
        missing.sort(key=lambda item: str(item.get("document_date") or ""), reverse=True)
        return {
            "ok": True,
            "period_start": f"{period_start[:4]}-{period_start[4:6]}-{period_start[6:]}",
            "period_end": f"{period_end[:4]}-{period_end[4:6]}-{period_end[6:]}",
            "project_dim_id": dim_id,
            "project_field": field,
            "checked": len(rows),
            "rows": missing,
        }

    def merit_bank_check(self, period: str | None = "last3") -> dict:
        start, end, period_label = selected_period_range(period)
        merit_rows_raw = self.load_merit_purchase_invoices_for_bank_period(period)
        if merit_rows_raw is None:
            return {"ok": False, "error": "Meriti ostuarvete päring ei õnnestunud."}
        merit_rows = [normalize_merit_purchase_row(row) for row in merit_rows_raw]
        bank_rows = [
            row for row in list_bank_transactions(self.connection)
            if in_selected_period(row.get("booking_date", ""), start, end)
        ]

        rows: list[dict[str, object]] = []
        matched_bank_indexes: set[int] = set()
        for merit in merit_rows:
            bank, bank_score, bank_reasons = best_merit_bank_match(merit, bank_rows, match_score_merit_bank)
            if bank and bank_score < 80:
                bank = None
            if not bank and not in_selected_period(merit.get("invoice_date", ""), start, end):
                continue
            bank_index = bank_rows.index(bank) if bank else None
            if bank_index is not None:
                matched_bank_indexes.add(bank_index)
            payment_status = merit.get("payment_status", "")
            if bank and payment_status in {"paid", "partially_paid"}:
                status = "ok_paid"
            elif bank and payment_status == "unpaid":
                status = "bank_paid_merit_unpaid"
            elif not bank and payment_status in {"paid", "partially_paid"}:
                status = "merit_paid_no_bank_match"
            else:
                status = "unpaid_no_bank_match"
            rows.append(
                {
                    "status": status,
                    "merit_invoice_date": merit.get("invoice_date", ""),
                    "supplier": merit.get("supplier", ""),
                    "invoice_number": merit.get("invoice_number", ""),
                    "merit_amount": money(merit.get("amount_total")),
                    "merit_paid_amount": money(merit.get("paid_amount")),
                    "merit_payment_status": payment_status,
                    "currency": merit.get("currency", "EUR"),
                    "bank_date": bank.get("booking_date", "") if bank else "",
                    "bank_amount": money(bank.get("amount")) if bank else "",
                    "bank_currency": bank.get("currency", "") if bank else "",
                    "bank_party": bank.get("party_name", "") if bank else "",
                    "bank_remittance": bank.get("remittance", "") if bank else "",
                    "bank_score": bank_score,
                    "bank_reasons": bank_reasons,
                }
            )

        for index, bank in enumerate(bank_rows):
            if bank.get("credit_debit") != "DBIT" or index in matched_bank_indexes:
                continue
            rows.append(
                {
                    "status": "bank_debit_no_merit",
                    "merit_invoice_date": "",
                    "supplier": "",
                    "invoice_number": invoice_number_from_bank_remittance(bank.get("remittance", "")),
                    "merit_amount": "",
                    "merit_paid_amount": "",
                    "merit_payment_status": "",
                    "currency": bank.get("currency", "EUR"),
                    "bank_date": bank.get("booking_date", ""),
                    "bank_amount": money(bank.get("amount")),
                    "bank_currency": bank.get("currency", ""),
                    "bank_party": bank.get("party_name", ""),
                    "bank_remittance": bank.get("remittance", ""),
                    "bank_score": "",
                    "bank_reasons": "",
                }
            )

        priority = {
            "bank_paid_merit_unpaid": 0,
            "bank_debit_no_merit": 1,
            "merit_paid_no_bank_match": 2,
            "unpaid_no_bank_match": 3,
            "ok_paid": 4,
        }
        rows.sort(key=lambda row: (priority.get(str(row.get("status")), 9), str(row.get("merit_invoice_date") or row.get("bank_date") or "")), reverse=False)
        summary: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "")
            summary[status] = summary.get(status, 0) + 1
        return {
            "ok": True,
            "period": period or "last3",
            "period_label": period_label,
            "merit_count": len(merit_rows),
            "bank_count": len(bank_rows),
            "summary": summary,
            "rows": rows,
        }

    def live_merit_bank_reconciliation_rows(self) -> list[dict[str, object]] | None:
        payload = self.merit_bank_check()
        if not payload.get("ok"):
            return None
        result: list[dict[str, object]] = []
        for row in payload.get("rows", []):
            status = str(row.get("status", ""))
            exists_merit = status != "bank_debit_no_merit"
            exists_bank = bool(row.get("bank_date"))
            result.append(
                {
                    "invoice_date": row.get("merit_invoice_date") or row.get("bank_date", ""),
                    "supplier": row.get("supplier") or row.get("bank_party", ""),
                    "invoice_number": row.get("invoice_number", ""),
                    "amount": row.get("merit_amount") or row.get("bank_amount", ""),
                    "exists_merit": exists_merit,
                    "exists_mail": False,
                    "exists_bank": exists_bank,
                    "merit_payment_status": row.get("merit_payment_status", ""),
                    "bank_payment_status": "paid" if exists_bank and exists_merit else ("bank_debit_no_merit" if status == "bank_debit_no_merit" else "no_bank_match"),
                    "bank_date": row.get("bank_date", ""),
                    "bank_amount": row.get("bank_amount", ""),
                    "bank_party": row.get("bank_party", ""),
                    "bank_remittance": row.get("bank_remittance", ""),
                    "source": "Merit" if exists_merit else "Pank",
                }
            )
        return result

    def send_invoice_to_merit(self, invoice_id: int, force: bool = False) -> dict:
        row = self.connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            return {"ok": False, "error": "Arvet ei leitud"}
        if row["merit_status"] == "sent" and not force:
            return {"ok": False, "error": "See arve on meie andmebaasi järgi juba Meritisse saadetud."}

        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        client = MeritClient(settings.get("merit_api_id", ""), settings.get("merit_api_key", ""))
        try:
            taxes = client.get_taxes()
            tax_id = find_tax_id(taxes, settings.get("merit_default_tax_pct", "24"))
            if not tax_id:
                return {
                    "ok": False,
                    "error": f"Meritist ei leitud KM määra {settings.get('merit_default_tax_pct', '24')}%. Kontrolli seadistust.",
                }
            project_dim_id, project_values, created_project_codes = ensure_merit_project_values(client, settings, row)
            preview = build_purchase_invoice_payload(
                row,
                include_attachment_content=True,
                item_code=settings.get("merit_default_item_code", DEFAULT_ITEM_CODE) or DEFAULT_ITEM_CODE,
                payment_method=settings.get("merit_payment_method", "Pank") or "Pank",
                tax_id=tax_id,
                gl_account_code=settings.get("merit_default_gl_account_code", DEFAULT_GL_ACCOUNT_CODE) or DEFAULT_GL_ACCOUNT_CODE,
                project_dimension_id=project_dim_id,
                project_values=project_values,
            )
            send_payload = preview["payload"]
            response = client.send_purchase_invoice(send_payload)
        except Exception as exc:
            error = str(exc)
            diagnostic = {"error": error}
            if "preview" in locals():
                diagnostic["payload"] = redact_attachment(preview["payload"])
            self.connection.execute(
                """
                UPDATE invoices
                SET merit_status = 'error',
                    merit_error = ?,
                    merit_response = ?
                WHERE id = ?
                """,
                (error, json.dumps(diagnostic, ensure_ascii=False), invoice_id),
            )
            self.connection.commit()
            return diagnostic | {"ok": False}

        response_json = json.dumps(response, ensure_ascii=False)
        sent_at = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """
            UPDATE invoices
            SET merit_status = 'sent',
                merit_sent_at = ?,
                merit_response = ?,
                merit_error = NULL
            WHERE id = ?
            """,
            (sent_at, response_json, invoice_id),
        )
        self.connection.execute(
            "INSERT INTO invoice_events (invoice_id, event_type, event_at, note) VALUES (?, ?, ?, ?)",
            (invoice_id, "merit_resent" if force else "merit_sent", sent_at, response_json[:1000]),
        )
        self.connection.commit()
        auto_payment = self.send_merit_payment_for_invoice_if_paid(invoice_id)
        return {
            "ok": True,
            "sent_at": sent_at,
            "response": response,
            "auto_payment": auto_payment,
            "created_project_codes": created_project_codes if "created_project_codes" in locals() else [],
            "preview": {**preview, "payload": "[sent with full attachment content]"},
        }

    def send_merit_payment_for_invoice_if_paid(self, invoice_id: int) -> dict:
        row = self.connection.execute(
            """
            SELECT payment_status, paid_amount, paid_date, invoice_number, amount_total
            FROM invoices
            WHERE id = ?
            """,
            (invoice_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "skipped": True, "reason": "Arvet ei leitud pärast Meritisse saatmist."}
        if row["payment_status"] != "paid":
            return {"ok": True, "skipped": True, "reason": "Meie andmebaasis ei ole arve pangas makstuks märgitud."}
        if not row["paid_amount"] or not row["paid_date"]:
            return {"ok": True, "skipped": True, "reason": "Pangamakse summa või kuupäev puudub."}
        if not money_amount_matches(row["amount_total"], row["paid_amount"]):
            return {
                "ok": True,
                "skipped": True,
                "reason": f"Arve summa {money(row['amount_total'])} ei klapi pangasummaga {money(row['paid_amount'])}.",
            }
        try:
            result = self.send_merit_payments(invoice_ids=[f"invoice:{invoice_id}"])
        except Exception as exc:
            return {"ok": False, "skipped": False, "error": str(exc)}
        if not result.get("sent"):
            errors = result.get("errors") or []
            reason = errors[0].get("error") if errors and isinstance(errors[0], dict) else "Sobivat maksekandidaati ei tekkinud."
            return {"ok": bool(result.get("ok")), "skipped": True, "reason": reason, "result": result}
        return result

    def merit_payment_candidates(self, period: str | None = "last3") -> dict:
        start, end, period_label = selected_period_range(period)
        rows = self.connection.execute(
            """
            SELECT id, invoice_number, invoice_date, issuer_name, amount_total, currency,
                   paid_amount, paid_date, bank_match_note, payment_status,
                   merit_status, merit_sent_at, merit_response, merit_payment_sent_at, merit_payment_error
            FROM invoices
            WHERE invoice_kind = 'purchase_candidate'
              AND merit_status = 'sent'
              AND payment_status = 'paid'
              AND COALESCE(paid_amount, '') != ''
              AND COALESCE(paid_date, '') != ''
              AND COALESCE(merit_payment_sent_at, '') = ''
              AND COALESCE(merit_payment_error, '') NOT LIKE '%Puudub selliste parameetritega tasumata ostuarve%'
            ORDER BY paid_date, issuer_name, invoice_number
            """
        ).fetchall()
        local_candidates: list[dict[str, object]] = []
        check_log: list[dict[str, str]] = []
        for row in rows:
            item = row_to_dict(row)
            local_bank_status = f"makstud {money(item.get('paid_amount'))} {item.get('currency') or 'EUR'} / {item.get('paid_date', '')}"
            local_merit_status = "makse märkimata"
            if item.get("merit_payment_sent_at"):
                local_merit_status = f"makseks märgitud {item.get('merit_payment_sent_at')}"
            elif item.get("merit_payment_error"):
                local_merit_status = f"viga: {item.get('merit_payment_error')}"
            elif item.get("merit_status") == "sent":
                local_merit_status = "arve saadetud, makse märkimata"
            log_item = {
                "invoice_id": str(item.get("id", "")),
                "invoice_number": str(item.get("invoice_number", "") or ""),
                "invoice_date": str(item.get("invoice_date", "") or ""),
                "supplier": str(item.get("issuer_name", "") or ""),
                "invoice_amount": money(item.get("amount_total")),
                "bank_amount": money(item.get("paid_amount")),
                "currency": str(item.get("currency") or "EUR"),
                "paid_date": str(item.get("paid_date", "") or ""),
                "local_bank_status": local_bank_status,
                "local_merit_status": local_merit_status,
                "live_merit_status": "",
                "reason": str(item.get("bank_match_note", "") or ""),
            }
            if not in_selected_period(item.get("paid_date", ""), start, end):
                check_log.append(log_item | {"result": "Vahele jäetud", "reason": "Pangamakse kuupäev ei ole valitud perioodis."})
                continue
            payment_date_for_merit = later_iso_date(item.get("paid_date", ""), item.get("invoice_date", ""))
            amount_matches = money_amount_matches(item.get("amount_total"), item.get("paid_amount"))
            warning = ""
            if not amount_matches:
                warning = f"Arve summa {money(item.get('amount_total'))} ei klapi pangasummaga {money(item.get('paid_amount'))}."
            local_candidates.append(
                {
                    "candidate_id": f"invoice:{item.get('id')}",
                    "source": "invoice",
                    "invoice_id": item.get("id"),
                    "invoice_number": item.get("invoice_number", ""),
                    "supplier": item.get("issuer_name", ""),
                    "payment_vendor": first_company_name(item.get("issuer_name", "")),
                    "amount": money(item.get("paid_amount") or item.get("amount_total")),
                    "invoice_amount": money(item.get("amount_total")),
                    "bank_amount": money(item.get("paid_amount")),
                    "currency": item.get("currency") or "EUR",
                    "invoice_date": item.get("invoice_date", ""),
                    "paid_date": item.get("paid_date", ""),
                    "payment_date_for_merit": payment_date_for_merit,
                    "payment_date_note": "Merit ei luba makset enne arve kuupäeva; kasutatakse arve kuupäeva." if payment_date_for_merit != item.get("paid_date", "") else "",
                    "bank_match_note": item.get("bank_match_note", ""),
                    "merit_response": item.get("merit_response", ""),
                    "selectable": amount_matches,
                    "default_checked": amount_matches,
                    "warning": warning,
                    "_log_item": log_item,
                }
            )
        payments: list[dict[str, object]] = []
        live_merit_rows = self.load_merit_purchase_invoices_for_payment_candidates(local_candidates) if local_candidates else []
        if live_merit_rows is None:
            for candidate in local_candidates:
                log_item = candidate.pop("_log_item", {})
                candidate["selectable"] = False
                candidate["default_checked"] = False
                candidate["warning"] = "Meriti live kontroll ebaõnnestus; makset ei saadeta automaatselt."
                check_log.append(log_item | {
                    "live_merit_status": "kontroll ebaõnnestus",
                    "result": "Ei saada",
                    "reason": candidate["warning"],
                })
            live_merit_rows = []
            local_candidates = []
        for candidate in local_candidates:
            log_item = candidate.pop("_log_item", {})
            live_row = find_matching_merit_row_for_payment(candidate, live_merit_rows)
            if live_row is None:
                candidate["selectable"] = False
                candidate["default_checked"] = False
                candidate["warning"] = "Meriti live kontrollis vastavat arvet ei leitud."
                check_log.append(log_item | {
                    "live_merit_status": "arvet ei leitud",
                    "result": "Ei saada",
                    "reason": candidate["warning"],
                })
                continue
            live_status = merit_payment_status_from_row(live_row)
            live_paid = money(merit_row_paid_amount(live_row))
            live_text = f"{live_status}; tasutud {live_paid or '0'} {candidate.get('currency') or 'EUR'}"
            if live_status in {"paid", "partially_paid"}:
                check_log.append(log_item | {
                    "live_merit_status": live_text,
                    "result": "Ei saada",
                    "reason": "Meriti live andmete järgi on arve juba makstud või osaliselt makstud.",
                })
                continue
            check_log.append(log_item | {
                "live_merit_status": live_text,
                "result": "Saadetav" if candidate.get("selectable") else "Vajab kontrolli",
                "reason": candidate.get("warning") or "Kohalik pank: makstud; kohalik Merit: makse märkimata; Meriti live: tasumata.",
            })
            payments.append(candidate)
        result = {"ok": True, "period": period or "last3", "period_label": period_label, "payments": payments, "count": len(payments), "checked": len(check_log), "check_log": check_log, "mode": "local_sent_paid_invoices"}
        return result
        if merit_rows is None:
            result["warning"] = "Meriti ostuarvete kontroll ei õnnestunud; pangakande-põhiseid kandidaate ei lisatud."
        return result

    def local_merit_payment_candidates_for_preview(self, period: str | None = "last3") -> tuple[list[dict[str, object]], list[dict[str, str]], str]:
        start, end, period_label = selected_period_range(period)
        rows = self.connection.execute(
            """
            SELECT id, invoice_number, invoice_date, issuer_name, amount_total, currency,
                   paid_amount, paid_date, bank_match_note, payment_status,
                   merit_status, merit_sent_at, merit_response, merit_payment_sent_at, merit_payment_error
            FROM invoices
            WHERE invoice_kind = 'purchase_candidate'
              AND merit_status = 'sent'
              AND payment_status = 'paid'
              AND COALESCE(paid_amount, '') != ''
              AND COALESCE(paid_date, '') != ''
              AND COALESCE(merit_payment_sent_at, '') = ''
              AND COALESCE(merit_payment_error, '') NOT LIKE '%Puudub selliste parameetritega tasumata ostuarve%'
            ORDER BY paid_date, issuer_name, invoice_number
            """
        ).fetchall()
        local_candidates: list[dict[str, object]] = []
        check_log: list[dict[str, str]] = []
        for row in rows:
            item = row_to_dict(row)
            local_bank_status = f"makstud {money(item.get('paid_amount'))} {item.get('currency') or 'EUR'} / {item.get('paid_date', '')}"
            local_merit_status = "makse markimata"
            if item.get("merit_payment_sent_at"):
                local_merit_status = f"makseks margitud {item.get('merit_payment_sent_at')}"
            elif item.get("merit_payment_error"):
                local_merit_status = f"viga: {item.get('merit_payment_error')}"
            elif item.get("merit_status") == "sent":
                local_merit_status = "arve saadetud, makse markimata"
            log_item = {
                "invoice_id": str(item.get("id", "")),
                "invoice_number": str(item.get("invoice_number", "") or ""),
                "invoice_date": str(item.get("invoice_date", "") or ""),
                "supplier": str(item.get("issuer_name", "") or ""),
                "invoice_amount": money(item.get("amount_total")),
                "bank_amount": money(item.get("paid_amount")),
                "currency": str(item.get("currency") or "EUR"),
                "paid_date": str(item.get("paid_date", "") or ""),
                "local_bank_status": local_bank_status,
                "local_merit_status": local_merit_status,
                "live_merit_status": "",
                "reason": str(item.get("bank_match_note", "") or ""),
            }
            if not in_selected_period(item.get("paid_date", ""), start, end):
                check_log.append(log_item | {"result": "Vahele jaetud", "reason": "Pangamakse kuupaev ei ole valitud perioodis."})
                continue
            payment_date_for_merit = later_iso_date(item.get("paid_date", ""), item.get("invoice_date", ""))
            amount_matches = money_amount_matches(item.get("amount_total"), item.get("paid_amount"))
            warning = ""
            if not amount_matches:
                warning = f"Arve summa {money(item.get('amount_total'))} ei klapi pangasummaga {money(item.get('paid_amount'))}."
            local_candidates.append(
                {
                    "candidate_id": f"invoice:{item.get('id')}",
                    "source": "invoice",
                    "invoice_id": item.get("id"),
                    "invoice_number": item.get("invoice_number", ""),
                    "supplier": item.get("issuer_name", ""),
                    "payment_vendor": first_company_name(item.get("issuer_name", "")),
                    "amount": money(item.get("paid_amount") or item.get("amount_total")),
                    "invoice_amount": money(item.get("amount_total")),
                    "bank_amount": money(item.get("paid_amount")),
                    "currency": item.get("currency") or "EUR",
                    "invoice_date": item.get("invoice_date", ""),
                    "paid_date": item.get("paid_date", ""),
                    "payment_date_for_merit": payment_date_for_merit,
                    "payment_date_note": "Merit ei luba makset enne arve kuupaeva; kasutatakse arve kuupaeva." if payment_date_for_merit != item.get("paid_date", "") else "",
                    "bank_match_note": item.get("bank_match_note", ""),
                    "merit_response": item.get("merit_response", ""),
                    "selectable": amount_matches,
                    "default_checked": amount_matches,
                    "warning": warning,
                    "_log_item": log_item,
                }
            )
        return local_candidates, check_log, period_label

    def stream_merit_payment_candidates(self, period: str | None = "last3"):
        local_candidates, skipped_logs, period_label = self.local_merit_payment_candidates_for_preview(period)
        payments: list[dict[str, object]] = []
        checked = 0
        yield {"type": "start", "period_label": period_label, "local_candidates": len(local_candidates), "skipped": len(skipped_logs)}
        for row in skipped_logs:
            checked += 1
            yield {"type": "log", "checked": checked, "row": row}
        for candidate in local_candidates:
            log_item = dict(candidate.get("_log_item", {}) or {})
            yield {"type": "log", "checked": checked + 1, "row": log_item | {"live_merit_status": "kontrollin...", "result": "Kontrollin", "reason": "Teen Meriti live paringu ainult sellele kohalikule kandidaadile."}}
            live_merit_rows = self.load_merit_purchase_invoices_for_payment_candidates([candidate])
            checked += 1
            candidate.pop("_log_item", None)
            if live_merit_rows is None:
                candidate["selectable"] = False
                candidate["default_checked"] = False
                candidate["warning"] = "Meriti live kontroll ebaonnestus; makset ei saadeta automaatselt."
                yield {"type": "log", "checked": checked, "row": log_item | {"live_merit_status": "kontroll ebaonnestus", "result": "Ei saada", "reason": candidate["warning"]}}
                continue
            live_row = find_matching_merit_row_for_payment(candidate, live_merit_rows)
            if live_row is None:
                candidate["selectable"] = False
                candidate["default_checked"] = False
                candidate["warning"] = "Meriti live kontrollis vastavat arvet ei leitud."
                yield {"type": "log", "checked": checked, "row": log_item | {"live_merit_status": "arvet ei leitud", "result": "Ei saada", "reason": candidate["warning"]}}
                continue
            live_status = merit_payment_status_from_row(live_row)
            live_paid = money(merit_row_paid_amount(live_row))
            live_text = f"{live_status}; tasutud {live_paid or '0'} {candidate.get('currency') or 'EUR'}"
            if live_status in {"paid", "partially_paid"}:
                yield {"type": "log", "checked": checked, "row": log_item | {"live_merit_status": live_text, "result": "Ei saada", "reason": "Meriti live andmete jargi on arve juba makstud voi osaliselt makstud."}}
                continue
            payments.append(candidate)
            yield {"type": "log", "checked": checked, "row": log_item | {"live_merit_status": live_text, "result": "Saadetav" if candidate.get("selectable") else "Vajab kontrolli", "reason": candidate.get("warning") or "Kohalik pank: makstud; kohalik Merit: makse markimata; Meriti live: tasumata."}}
        yield {"type": "done", "period_label": period_label, "checked": checked, "payments": payments, "count": len(payments)}

    def load_merit_purchase_invoices_for_bank_period(self, period: str | None = "last3") -> list[dict] | None:
        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        if not settings.get("merit_api_id") or not settings.get("merit_api_key"):
            return None
        selected_start, selected_end, _period_label = selected_period_range(period)
        dates = [
            str(row["booking_date"])[:10]
            for row in self.connection.execute(
                "SELECT booking_date FROM bank_transactions WHERE COALESCE(booking_date, '') != ''"
            ).fetchall()
        ]
        parsed_dates = [value for value in (parse_iso_day(date) for date in dates) if value is not None]
        end = max(parsed_dates) if parsed_dates else datetime.now()
        if selected_end:
            end = selected_end
        query_start = selected_start - timedelta(days=365) if selected_start else None
        start = query_start or (datetime((min(parsed_dates).year if parsed_dates else end.year) - 1, 1, 1))
        client = MeritClient(settings.get("merit_api_id", ""), settings.get("merit_api_key", ""))
        collected: list[dict] = []
        seen: set[str] = set()
        try:
            for period_start, period_end in quarter_periods(start.year, end):
                chunk_start = parse_iso_day(f"{period_start[:4]}-{period_start[4:6]}-{period_start[6:]}")
                chunk_end = parse_iso_day(f"{period_end[:4]}-{period_end[4:6]}-{period_end[6:]}")
                if chunk_end and chunk_end < start:
                    continue
                if chunk_start and chunk_start > end:
                    continue
                if chunk_start and chunk_start < start:
                    period_start = start.strftime("%Y%m%d")
                if chunk_end and chunk_end > end:
                    period_end = end.strftime("%Y%m%d")
                rows = client.get_purchase_invoices(period_start, period_end, unpaid=False)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    doc_date = parse_iso_day(str(row.get("DocumentDate", "") or "")[:10])
                    if selected_end and doc_date and doc_date > selected_end:
                        continue
                    key = str(row.get("PIHId") or "") or "|".join(
                        str(row.get(part, "")) for part in ("DocumentDate", "VendorName", "BillNo", "TotalSum")
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(row)
        except MeritApiError:
            return None
        return collected

    def load_merit_purchase_invoices_for_payment_candidates(self, candidates: list[dict[str, object]]) -> list[dict] | None:
        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        if not settings.get("merit_api_id") or not settings.get("merit_api_key"):
            return None
        dates = []
        for item in candidates:
            for key in ("invoice_date", "paid_date"):
                parsed = parse_iso_day(str(item.get(key, "") or ""))
                if parsed is not None:
                    dates.append(parsed)
        if not dates:
            return []
        start = min(dates)
        end = max(dates)
        client = MeritClient(settings.get("merit_api_id", ""), settings.get("merit_api_key", ""))
        collected: list[dict] = []
        seen: set[str] = set()
        try:
            for period_start, period_end in quarter_periods(start.year, end):
                chunk_start = parse_iso_day(f"{period_start[:4]}-{period_start[4:6]}-{period_start[6:]}")
                chunk_end = parse_iso_day(f"{period_end[:4]}-{period_end[4:6]}-{period_end[6:]}")
                if chunk_end and chunk_end < start:
                    continue
                if chunk_start and chunk_start > end:
                    continue
                if chunk_start and chunk_start < start:
                    period_start = start.strftime("%Y%m%d")
                if chunk_end and chunk_end > end:
                    period_end = end.strftime("%Y%m%d")
                rows = client.get_purchase_invoices(period_start, period_end, unpaid=False)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    key = str(row.get("PIHId") or "") or "|".join(
                        str(row.get(part, "")) for part in ("DocumentDate", "VendorName", "BillNo", "TotalSum")
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(row)
        except MeritApiError:
            return None
        return collected

    def bank_only_merit_payment_candidates(self, merit_rows: list[dict] | None, period: str | None = "last3") -> list[dict[str, object]]:
        if merit_rows is None:
            return []
        start, end, _period_label = selected_period_range(period)
        merit_by_signature: dict[tuple[str, Decimal], list[dict]] = {}
        for merit_row in merit_rows:
            signature = merit_row_signature(merit_row)
            if signature[0] and signature[1]:
                merit_by_signature.setdefault(signature, []).append(merit_row)
        sent_keys = {
            str(row["candidate_key"])
            for row in self.connection.execute(
                "SELECT candidate_key FROM merit_external_payments WHERE COALESCE(sent_at, '') != '' OR COALESCE(error, '') LIKE '%Puudub selliste parameetritega tasumata ostuarve%'"
            ).fetchall()
        }
        local_rows = self.connection.execute(
            "SELECT invoice_number, amount_total FROM invoices WHERE COALESCE(invoice_number, '') != ''"
        ).fetchall()
        local_keys = {
            (norm_lookup(str(row["invoice_number"])), decimal_value(str(row["amount_total"])).quantize(Decimal("0.01")))
            for row in local_rows
        }
        rows = self.connection.execute(
            """
            SELECT id, booking_date, amount, currency, party_name, remittance
            FROM bank_transactions
            WHERE credit_debit = 'DBIT'
              AND COALESCE(amount, '') != ''
              AND COALESCE(party_name, '') != ''
              AND COALESCE(remittance, '') != ''
            ORDER BY booking_date, party_name
            """
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = row_to_dict(row)
            if not in_selected_period(item.get("booking_date", ""), start, end):
                continue
            invoice_number = invoice_number_from_bank_remittance(item.get("remittance", ""))
            if not invoice_number:
                continue
            candidate_key = f"bank:{item.get('id')}"
            if candidate_key in sent_keys:
                continue
            amount_key = decimal_value(str(item.get("amount"))).quantize(Decimal("0.01"))
            if (norm_lookup(invoice_number), amount_key) in local_keys:
                continue
            merit_matches = merit_by_signature.get((norm_lookup(invoice_number), amount_key), [])
            if not merit_matches:
                continue
            unpaid_merit = [merit_row for merit_row in merit_matches if not merit_row_is_paid(merit_row)]
            if not unpaid_merit:
                continue
            merit_row = unpaid_merit[0]
            merit_supplier = str(merit_row.get("VendorName") or item.get("party_name", ""))
            result.append(
                {
                    "candidate_id": candidate_key,
                    "source": "bank",
                    "invoice_id": "",
                    "bank_id": item.get("id"),
                    "invoice_number": invoice_number,
                    "supplier": merit_supplier,
                    "payment_vendor": first_company_name(merit_supplier),
                    "amount": money(item.get("amount")),
                    "invoice_amount": "",
                    "bank_amount": money(item.get("amount")),
                    "currency": item.get("currency") or "EUR",
                    "invoice_date": str(merit_row.get("DocumentDate") or ""),
                    "paid_date": str(item.get("booking_date", ""))[:10],
                    "payment_date_for_merit": str(item.get("booking_date", ""))[:10],
                    "payment_date_note": "",
                    "bank_match_note": f"Meritis tasumata; pangakanne {item.get('id')}: {item.get('remittance', '')}",
                    "merit_response": "",
                    "selectable": True,
                    "default_checked": False,
                    "warning": "Ainult pangakande põhjal. Kontrolli, et arve on Meritis olemas ja tasumata.",
                }
            )
        return result

    def merit_paid_invoice_ids_from_comparison(self) -> set[str]:
        paid_ids: set[str] = set()
        for row in read_csv_dicts(self.comparison_dir() / "merit_bank_mail_summary.csv"):
            status = str(row.get("merit_payment_status", "")).strip().lower()
            mail_invoice_id = str(row.get("mail_invoice_id", "")).strip()
            if mail_invoice_id and status in {"paid", "partially_paid"}:
                paid_ids.add(mail_invoice_id)
        return paid_ids

    def send_merit_payments(self, invoice_ids: list[str] | None = None, period: str | None = "last3") -> dict:
        selected_ids = {str(value) for value in (invoice_ids or []) if value}
        candidates = self.merit_payment_candidates(period)["payments"]
        if selected_ids:
            candidates = [item for item in candidates if str(item.get("candidate_id") or item.get("invoice_id")) in selected_ids]
        candidates = [item for item in candidates if item.get("selectable", True)]
        if not candidates:
            return {"ok": False, "sent": [], "errors": [{"error": "Valitud arvete hulgas ei olnud saatmiseks sobivaid makseid."}]}

        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        debtor_iban = settings.get("payment_debtor_iban", "")
        client = MeritClient(settings.get("merit_api_id", ""), settings.get("merit_api_key", ""))
        banks = client.get_banks()
        bank = find_merit_bank(banks, debtor_iban)
        if not bank:
            raise MeritApiError("Meriti pankade nimekirjast ei leitud sobivat pangakontot.")
        bank_id = str(bank.get("BankId", ""))
        bank_iban = str(bank.get("IBANCode", "") or debtor_iban)
        if not bank_id:
            raise MeritApiError("Meriti pangakontol puudub BankId.")

        sent: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        for item in candidates:
            candidate_id = str(item.get("candidate_id") or f"invoice:{item.get('invoice_id')}")
            vendor_name = resolve_merit_vendor_name(client, item)
            payload = {
                "BankId": bank_id,
                "IBAN": bank_iban,
                "VendorName": vendor_name or item["supplier"],
                "PaymentDate": merit_payment_date(str(item.get("payment_date_for_merit") or item["paid_date"])),
                "BillNo": item["invoice_number"],
                "RefNo": "",
                "Amount": item["amount"],
            }
            if str(item.get("currency") or "EUR").upper() != "EUR":
                payload["CurrencyCode"] = str(item.get("currency")).upper()
            try:
                response = client.send_purchase_payment(payload)
            except Exception as exc:
                error = str(exc)
                if merit_error_means_no_unpaid_invoice(error):
                    sent_at = datetime.now().isoformat(timespec="seconds")
                    note = json.dumps({"message": "Merit teatas, et tasumata ostuarvet ei ole; märgitud lokaalselt Meritis juba makstuks.", "payload": payload, "error": error}, ensure_ascii=False)
                    self.mark_merit_payment_result(item, sent_at, note, "merit_payment_already_paid")
                    sent.append({"candidate_id": candidate_id, "invoice_id": item.get("invoice_id"), "invoice_number": item["invoice_number"], "response": {"already_paid_in_merit": True}})
                    continue
                self.mark_merit_payment_error(item, error)
                errors.append({"candidate_id": candidate_id, "invoice_id": item.get("invoice_id"), "invoice_number": item["invoice_number"], "error": error, "payload": payload})
                continue
            sent_at = datetime.now().isoformat(timespec="seconds")
            response_json = json.dumps(response, ensure_ascii=False)
            self.mark_merit_payment_result(item, sent_at, response_json, "merit_payment_sent")
            sent.append({"candidate_id": candidate_id, "invoice_id": item.get("invoice_id"), "invoice_number": item["invoice_number"], "response": response})
        self.connection.commit()
        return {"ok": not errors, "sent": sent, "errors": errors, "bank": {"BankId": bank_id, "IBAN": bank_iban}}

    def mark_merit_payment_result(self, item: dict, sent_at: str, response_json: str, event_type: str) -> None:
        if item.get("source") == "bank":
            self.connection.execute(
                """
                INSERT INTO merit_external_payments (
                    candidate_key, source_type, source_id, invoice_number, supplier, amount,
                    currency, paid_date, sent_at, response, error
                )
                VALUES (?, 'bank', ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(candidate_key) DO UPDATE SET
                    sent_at = excluded.sent_at,
                    response = excluded.response,
                    error = NULL
                """,
                (
                    item.get("candidate_id"),
                    str(item.get("bank_id", "")),
                    item.get("invoice_number", ""),
                    item.get("supplier", ""),
                    item.get("amount", ""),
                    item.get("currency", "EUR"),
                    item.get("paid_date", ""),
                    sent_at,
                    response_json,
                ),
            )
            return
        invoice_id = int(item["invoice_id"])
        self.connection.execute(
            """
            UPDATE invoices
            SET merit_payment_sent_at = ?,
                merit_payment_response = ?,
                merit_payment_error = NULL
            WHERE id = ?
            """,
            (sent_at, response_json, invoice_id),
        )
        self.connection.execute(
            "INSERT INTO invoice_events (invoice_id, event_type, event_at, note) VALUES (?, ?, ?, ?)",
            (invoice_id, event_type, sent_at, response_json[:1000]),
        )

    def mark_merit_payment_error(self, item: dict, error: str) -> None:
        if item.get("source") == "bank":
            self.connection.execute(
                """
                INSERT INTO merit_external_payments (
                    candidate_key, source_type, source_id, invoice_number, supplier, amount,
                    currency, paid_date, sent_at, response, error
                )
                VALUES (?, 'bank', ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                ON CONFLICT(candidate_key) DO UPDATE SET error = excluded.error
                """,
                (
                    item.get("candidate_id"),
                    str(item.get("bank_id", "")),
                    item.get("invoice_number", ""),
                    item.get("supplier", ""),
                    item.get("amount", ""),
                    item.get("currency", "EUR"),
                    item.get("paid_date", ""),
                    error,
                ),
            )
            return
        self.connection.execute(
            "UPDATE invoices SET merit_payment_error = ? WHERE id = ?",
            (error, int(item["invoice_id"])),
        )

    def comparison_dir(self) -> Path:
        candidates: list[Path] = []
        for base in (Path.cwd(), self.csv_path.resolve().parent, self.db_path.resolve().parent):
            candidates.append(base / "merit_bank_mail_compare")
            candidates.append(base.parent / "merit_bank_mail_compare")
            if len(base.parents) > 1:
                candidates.append(base.parents[1] / "merit_bank_mail_compare")
        for candidate in candidates:
            if (candidate / "merit_bank_mail_summary.csv").exists():
                return candidate
        return Path.cwd().parent / "merit_bank_mail_compare"

    def list_mail_reconciliation_rows(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT id, status, invoice_number, invoice_date, issuer_name, amount_total,
                   payment_status, paid_amount, paid_date, bank_match_note, subject,
                   import_source, merit_status, merit_sent_at, merit_payment_sent_at
            FROM invoices
            WHERE invoice_kind = 'purchase_candidate'
            ORDER BY invoice_date DESC, issuer_name
            """
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = row_to_dict(row)
            sent_to_merit = item.get("merit_status") == "sent"
            result.append(
                {
                    "invoice_date": item.get("invoice_date", ""),
                    "supplier": item.get("issuer_name", ""),
                    "invoice_number": item.get("invoice_number", ""),
                    "amount": money(item.get("amount_total")),
                    "exists_merit": sent_to_merit,
                    "exists_mail": True,
                    "exists_bank": bool(item.get("paid_date") or item.get("paid_amount")),
                    "merit_payment_status": "paid" if item.get("merit_payment_sent_at") else ("unpaid" if sent_to_merit else ""),
                    "bank_payment_status": item.get("payment_status", ""),
                    "bank_date": item.get("paid_date", ""),
                    "bank_amount": money(item.get("paid_amount")),
                    "bank_party": "",
                    "bank_remittance": item.get("bank_match_note", ""),
                    "source": "Käsitsi" if item.get("import_source") == "manual_upload" else "Mail",
                    "mail_status": item.get("status", ""),
                    "subject": item.get("subject", ""),
                    "mail_invoice_id": item.get("id", ""),
                    "import_source": item.get("import_source", ""),
                }
            )
        return result

    def add_manual_upload(self, fields: dict[str, str], file_info: dict[str, object]) -> dict:
        content = file_info.get("content", b"")
        if not isinstance(content, bytes) or not content:
            raise ValueError("Üleslaetud fail on tühi.")
        original_name = str(file_info.get("filename") or "arve.pdf")
        invoice_date = fields.get("invoice_date") or datetime.now().date().isoformat()
        month = invoice_date[:7] if re.match(r"^\d{4}-\d{2}", invoice_date) else datetime.now().strftime("%Y-%m")
        file_hash = hashlib.sha256(content).hexdigest()
        upload_dir = self.db_path.resolve().parent / "manual_uploads" / month
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved_name = f"{file_hash[:12]}_{safe_filename(original_name)}"
        saved_path = upload_dir / saved_name
        if not saved_path.exists():
            saved_path.write_bytes(content)

        data = {
            "fingerprint": "manual:" + file_hash,
            "invoice_kind": "purchase_candidate",
            "invoice_number": fields.get("invoice_number", ""),
            "invoice_date": invoice_date,
            "issuer_name": fields.get("issuer_name", ""),
            "issuer_email": "",
            "payment_details": "",
            "amount_total": "",
            "vat_amount": "",
            "due_date": "",
            "issuer_reg_code": "",
            "issuer_vat_no": "",
            "currency": "EUR",
            "subject": f"Käsitsi üles laaditud arve: {original_name}",
            "attachment_names": original_name,
            "attachment_paths": str(saved_path),
            "source_folder": "Käsitsi üleslaadimine",
            "import_source": "manual_upload",
            "review_note": fields.get("review_note", "") or "Käsitsi üles laaditud arve fail.",
        }
        row = upsert_seen(self.connection, data)
        return row_to_dict(row) | {"is_duplicate": "false"}

    def add_bank_upload(self, file_info: dict[str, object]) -> dict:
        content = file_info.get("content", b"")
        if not isinstance(content, bytes) or not content:
            raise ValueError("Üleslaetud panga väljavõte on tühi.")
        original_name = str(file_info.get("filename") or "statement.xml")
        if not original_name.lower().endswith(".xml"):
            raise ValueError("Praegu toetame panga väljavõtte importimisel ISO XML / CAMT faili.")

        file_hash = hashlib.sha256(content).hexdigest()
        upload_dir = self.db_path.resolve().parent / "bank_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved_path = upload_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_hash[:12]}_{safe_filename(original_name)}"
        saved_path.write_bytes(content)

        summary, entries = parse_statement(saved_path)
        database_summary = upsert_bank_transactions(self.connection, entries, str(saved_path))

        bank_csv = upload_dir / f"{saved_path.stem}_transactions.csv"
        write_bank_csv(bank_csv, entries)
        reconcile_dir = self.db_path.resolve().parent / "bank_reconcile"
        reconcile_summary = reconcile_bank(bank_csv, self.db_path, reconcile_dir)

        compare_summary = None
        merit_csv = self.find_merit_csv()
        if merit_csv:
            compare_summary = compare_merit_bank_mail(
                merit_csv,
                None,
                self.db_path,
                self.db_path,
                self.db_path.resolve().parent / "merit_bank_mail_compare",
            )

        return {
            "ok": True,
            "filename": original_name,
            "saved_path": str(saved_path),
            "transactions_csv": str(bank_csv),
            "summary": summary,
            "database": database_summary,
            "reconcile": reconcile_summary,
            "compare": compare_summary,
            "merit_csv": str(merit_csv) if merit_csv else "",
        }

    def find_merit_csv(self) -> Path | None:
        base = self.db_path.resolve().parent
        candidates = [
            base / "merit_ostuarved.csv",
            base / "merit_purchase_invoices.csv",
            base / "merit_bank_mail_compare" / "merit_ostuarved.csv",
            base / "merit_bank_mail_compare" / "merit_purchase_invoices.csv",
        ]
        for path in candidates:
            if path.exists():
                return path
        for path in base.rglob("*.csv"):
            name = path.name.lower()
            if "merit" in name and ("ostuarv" in name or "purchase" in name):
                return path
        return None

    def reconciliation_rows(self) -> dict[str, list[dict[str, object]]]:
        compare_dir = self.comparison_dir()
        summary_rows = read_csv_dicts(compare_dir / "merit_bank_mail_summary.csv")
        mail_missing_rows = read_csv_dicts(compare_dir / "mail_invoices_missing_in_merit.csv")
        bank_debit_rows = bank_debit_rows_for_reconciliation(self.connection)

        combined: list[dict[str, object]] = []
        merit: list[dict[str, object]] = []
        combined_mail_ids: set[str] = set()
        combined_by_key: dict[tuple[str, Decimal], dict[str, object]] = {}

        for row in summary_rows:
            if row.get("mail_invoice_id"):
                combined_mail_ids.add(str(row.get("mail_invoice_id")))
            item = {
                "invoice_date": row.get("merit_invoice_date", ""),
                "supplier": row.get("merit_supplier", ""),
                "invoice_number": row.get("merit_invoice_number", ""),
                "amount": money(row.get("merit_amount")),
                "exists_merit": True,
                "exists_mail": bool(row.get("mail_invoice_id")),
                "exists_bank": bool(row.get("bank_date")),
                "merit_payment_status": row.get("merit_payment_status", ""),
                "bank_payment_status": paid_label_from_bank(row),
                "bank_date": row.get("bank_date", ""),
                "bank_amount": money(row.get("bank_amount")),
                "bank_party": row.get("bank_party", ""),
                "bank_remittance": row.get("bank_remittance", ""),
                "source": "Merit",
            }
            merit.append(item)
            combined.append(item)
            key = invoice_merge_key(item.get("invoice_number", ""), item.get("amount", ""))
            if key[0] and key[1]:
                combined_by_key[key] = item

        for row in mail_missing_rows:
            if row.get("mail_invoice_id"):
                combined_mail_ids.add(str(row.get("mail_invoice_id")))
            local_invoice = None
            if row.get("mail_invoice_id"):
                local_invoice = self.connection.execute(
                    "SELECT merit_status, merit_payment_sent_at FROM invoices WHERE id = ?",
                    (row.get("mail_invoice_id"),),
                ).fetchone()
            local_sent_to_merit = bool(local_invoice and local_invoice["merit_status"] == "sent")
            mail_item = {
                "invoice_date": row.get("invoice_date", ""),
                "supplier": row.get("issuer_name", ""),
                "invoice_number": row.get("invoice_number", ""),
                "amount": money(row.get("amount_total")),
                "exists_merit": local_sent_to_merit,
                "exists_mail": True,
                "exists_bank": row.get("payment_status") == "paid",
                "merit_payment_status": "paid" if local_invoice and local_invoice["merit_payment_sent_at"] else ("unpaid" if local_sent_to_merit else ""),
                "bank_payment_status": row.get("payment_status", ""),
                "bank_date": "",
                "bank_amount": "",
                "bank_party": "",
                "bank_remittance": row.get("subject", ""),
                "source": "Mail",
                "mail_invoice_id": row.get("mail_invoice_id", ""),
            }
            key = invoice_merge_key(mail_item.get("invoice_number", ""), mail_item.get("amount", ""))
            existing = combined_by_key.get(key)
            if existing:
                existing["exists_mail"] = True
                existing["mail_invoice_id"] = mail_item.get("mail_invoice_id", "")
                if mail_item.get("exists_bank"):
                    existing["exists_bank"] = True
                    existing["bank_payment_status"] = mail_item.get("bank_payment_status", "")
                    existing["bank_date"] = mail_item.get("bank_date", "")
                    existing["bank_amount"] = mail_item.get("bank_amount", "")
                    existing["bank_remittance"] = mail_item.get("bank_remittance", "")
                existing["source"] = "Merit+Mail"
            else:
                combined.append(mail_item)
                if key[0] and key[1]:
                    combined_by_key[key] = mail_item

        for row in self.list_mail_reconciliation_rows():
            mail_id = str(row.get("mail_invoice_id", ""))
            if mail_id and mail_id not in combined_mail_ids:
                key = invoice_merge_key(row.get("invoice_number", ""), row.get("amount", ""))
                existing = combined_by_key.get(key)
                if existing:
                    existing["exists_mail"] = True
                    existing["mail_invoice_id"] = row.get("mail_invoice_id", "")
                    if row.get("exists_bank"):
                        existing["exists_bank"] = True
                        existing["bank_payment_status"] = row.get("bank_payment_status", "")
                        existing["bank_date"] = row.get("bank_date", "")
                        existing["bank_amount"] = row.get("bank_amount", "")
                        existing["bank_remittance"] = row.get("bank_remittance", "")
                    if existing.get("exists_merit") or row.get("exists_merit"):
                        existing["exists_merit"] = True
                        existing["source"] = "Merit+Mail"
                    else:
                        existing["source"] = existing.get("source", "Mail")
                else:
                    combined.append(row)
                    if key[0] and key[1]:
                        combined_by_key[key] = row
                combined_mail_ids.add(mail_id)

        for row in bank_debit_rows:
            existing_bank_target = find_bank_merge_target(row, combined)
            if existing_bank_target:
                attach_bank_row_to_reconciliation_item(existing_bank_target, row)
                continue
            combined.append(
                {
                    "invoice_date": row.get("booking_date", ""),
                    "supplier": row.get("party_name", ""),
                    "invoice_number": invoice_number_from_bank_remittance(row.get("remittance", "")),
                    "amount": money(row.get("amount")),
                    "exists_merit": False,
                    "exists_mail": False,
                    "exists_bank": True,
                    "merit_payment_status": "",
                    "bank_payment_status": "bank_debit_no_merit",
                    "bank_date": row.get("booking_date", ""),
                    "bank_amount": money(row.get("amount")),
                    "bank_party": row.get("party_name", ""),
                    "bank_remittance": row.get("remittance", ""),
                    "source": "Pank",
                }
            )

        combined.sort(key=lambda item: str(item.get("invoice_date") or ""), reverse=True)
        merit.sort(key=lambda item: str(item.get("invoice_date") or ""), reverse=True)
        return {
            "combined": combined,
            "merit": merit,
            "mail": self.list_mail_reconciliation_rows(),
        }

    def update_invoice(self, invoice_id: int, payload: dict) -> dict:
        status = payload.get("status", "pending")
        fields = payload.get("fields", {}) or {}
        note = payload.get("note", "") or ""
        update_status(self.connection, invoice_id, status, note=note, fields=fields)
        row = self.connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        return row_to_dict(row)

    def extract_invoice(self, invoice_id: int) -> dict:
        current = self.connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if current is None:
            return {"message": "Arvet ei leitud"}
        if not (current["attachment_paths"] or "").strip():
            return {
                "invoice": row_to_dict(current),
                "message": "PDF/XML faili ei ole salvestatud. Tee uus skänn lülitiga -SaveCandidateAttachments.",
            }
        extract_for_db(self.db_path, invoice_id=invoice_id, status="all")
        row = self.connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        return {"invoice": row_to_dict(row), "message": row["extraction_note"] or row["extraction_status"]}

    def merit_preview(self, invoice_id: int) -> dict:
        row = self.connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            return {"error": "Arvet ei leitud"}
        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        return build_purchase_invoice_payload(
            row,
            include_attachment_content=False,
            item_code=settings.get("merit_default_item_code", DEFAULT_ITEM_CODE) or DEFAULT_ITEM_CODE,
            payment_method=settings.get("merit_payment_method", "Pank") or "Pank",
            gl_account_code=settings.get("merit_default_gl_account_code", DEFAULT_GL_ACCOUNT_CODE) or DEFAULT_GL_ACCOUNT_CODE,
            project_dimension_id=configured_project_dim_id(settings),
        )

    def payment_file(self, invoice_id: int) -> dict:
        row = self.connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            return {"ok": False, "error": "Arvet ei leitud"}
        settings = get_settings(self.connection, MERIT_SETTING_KEYS)
        try:
            payment_file = build_sepa_payment_xml(
                row,
                debtor_name=settings.get("payment_debtor_name", "ERLIN OÜ") or "ERLIN OÜ",
                debtor_iban=settings.get("payment_debtor_iban", ""),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        export_dir = self.db_path.resolve().parent / "payment_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / payment_file.filename
        export_path.write_text(payment_file.xml, encoding="utf-8")
        event_at = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            "INSERT INTO invoice_events (invoice_id, event_type, event_at, note) VALUES (?, 'payment_file_created', ?, ?)",
            (invoice_id, event_at, str(export_path)),
        )
        self.connection.commit()
        return {
            "ok": True,
            "filename": payment_file.filename,
            "xml": payment_file.xml,
            "summary": payment_file.summary,
            "warnings": payment_file.warnings,
            "saved_path": str(export_path),
        }


def make_handler(app: InvoiceWebApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def send_text(self, body: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_text(json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8", status)

        def send_sse(self, events) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            for event in events:
                data = json.dumps(event, ensure_ascii=False).encode("utf-8")
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()
            self.close_connection = True

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_text(APP_HTML, "text/html; charset=utf-8")
            elif parsed.path == "/static/app.css":
                self.send_text(APP_CSS, "text/css; charset=utf-8")
            elif parsed.path == "/static/app.js":
                self.send_text(APP_JS, "application/javascript; charset=utf-8")
            elif parsed.path == "/api/invoices":
                self.send_json(app.list_invoices())
            elif parsed.path == "/api/reconciliation":
                self.send_json(app.reconciliation_rows())
            elif parsed.path == "/api/merit/settings":
                self.send_json(app.merit_settings())
            elif parsed.path == "/api/merit/payment-preview":
                try:
                    period = parse_qs(parsed.query).get("period", ["last3"])[0]
                    self.send_json(app.merit_payment_candidates(period))
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            elif parsed.path == "/api/merit/payment-preview-stream":
                try:
                    period = parse_qs(parsed.query).get("period", ["last3"])[0]
                    self.send_sse(app.stream_merit_payment_candidates(period))
                except Exception as exc:
                    self.send_sse([{"type": "error", "error": str(exc)}])
            elif parsed.path == "/api/merit/project-missing":
                try:
                    self.send_json(app.merit_project_missing())
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            elif parsed.path == "/api/merit/bank-check":
                try:
                    period = parse_qs(parsed.query).get("period", ["last3"])[0]
                    self.send_json(app.merit_bank_check(period))
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            elif parsed.path.startswith("/api/invoices/") and parsed.path.endswith("/merit-preview"):
                try:
                    invoice_id = int(parsed.path.split("/")[-2])
                    self.send_json(app.merit_preview(invoice_id))
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/invoices/") and parsed.path.endswith("/extract"):
                try:
                    invoice_id = int(parsed.path.split("/")[-2])
                    self.send_json(app.extract_invoice(invoice_id))
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/merit/settings":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw_body = self.rfile.read(length)
                    payload = json.loads(raw_body.decode("utf-8") or "{}")
                    self.send_json(app.save_merit_settings(payload))
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/merit/test":
                try:
                    self.send_json(app.test_merit_connection())
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/merit/send-payments":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw_body = self.rfile.read(length) if length else b"{}"
                    payload = json.loads(raw_body.decode("utf-8") or "{}")
                    invoice_ids = [str(value) for value in payload.get("invoice_ids", [])]
                    period = str(payload.get("period", "last3") or "last3")
                    self.send_json(app.send_merit_payments(invoice_ids=invoice_ids, period=period))
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/manual-upload":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw_body = self.rfile.read(length)
                    fields, files = parse_multipart_form(raw_body, self.headers.get("Content-Type", ""))
                    file_info = files.get("invoice_file")
                    if not file_info:
                        raise ValueError("Fail puudub.")
                    invoice = app.add_manual_upload(fields, file_info)
                    self.send_json({"ok": True, "invoice": invoice})
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/bank-upload":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw_body = self.rfile.read(length)
                    fields, files = parse_multipart_form(raw_body, self.headers.get("Content-Type", ""))
                    file_info = files.get("bank_statement_file")
                    if not file_info:
                        raise ValueError("Panga väljavõtte fail puudub.")
                    self.send_json(app.add_bank_upload(file_info))
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path.startswith("/api/invoices/") and parsed.path.endswith("/send-merit"):
                try:
                    invoice_id = int(parsed.path.split("/")[-2])
                    query = parse_qs(parsed.query)
                    force = str(query.get("force", ["false"])[0]).lower() in {"1", "true", "yes"}
                    self.send_json(app.send_invoice_to_merit(invoice_id, force=force))
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path.startswith("/api/invoices/") and parsed.path.endswith("/payment-file"):
                try:
                    invoice_id = int(parsed.path.split("/")[-2])
                    self.send_json(app.payment_file(invoice_id))
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path.startswith("/api/invoices/"):
                try:
                    invoice_id = int(parsed.path.rsplit("/", 1)[-1])
                    length = int(self.headers.get("Content-Length", "0"))
                    raw_body = self.rfile.read(length)
                    try:
                        text_body = raw_body.decode("utf-8")
                    except UnicodeDecodeError:
                        text_body = raw_body.decode("cp1257", errors="replace")
                    payload = json.loads(text_body or "{}")
                    self.send_json({"invoice": app.update_invoice(invoice_id, payload)})
                except Exception as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local browser UI for invoice review.")
    parser.add_argument("--csv", type=Path, default=Path("invoice_scan_output/clean_invoice_candidates.csv"))
    parser.add_argument("--db", type=Path, default=Path("invoice_register.sqlite"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    app = InvoiceWebApp(args.csv, args.db)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"Arvete kasutajaliides: http://{args.host}:{args.port}")
    print(f"CSV: {args.csv}")
    print(f"Andmebaas: {args.db}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
