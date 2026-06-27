# Arvete automatiseerimise tarkvara spetsifikatsioon

Viimati uuendatud: 2026-06-27

## 1. Eesmärk

Tarkvara eesmärk on aidata ERLIN OÜ ostuarvete menetlemisel:

- leida Outlooki PST failist või käsitsi üles laaditud failidest võimalikud ostuarved;
- lugeda arvetelt olulised andmed;
- lasta kasutajal kinnitada, kas tegu on päris ja õigustatud ostuarvega;
- salvestada kinnitatud arved andmebaasi;
- võrrelda arveid pangaväljavõttega;
- võrrelda arveid Meriti ostuarvetega;
- saata puuduvad ostuarved Meritisse;
- märkida pangas makstud arved Meritisse makstuks;
- valmistada tulevikus ette EMTA KMD/KMD INF ekspordi ja pangamaksete töövoog.

Rakendus on praegu Pythonil põhinev lokaalne veebirakendus, mis jookseb brauseris aadressil `http://127.0.0.1:8765`.

## 2. Peamised komponendid

### 2.1 PST ja e-kirjade skaneerimine

Moodulid:

- `pst_reader.py`
- `detection.py`
- `writers.py`
- `clean_results.py`
- `review_invoices.py`

Sisend:

- Outlooki `.pst` fail või sellest eksporditud osa.

Väljund:

- CSV kandidaatidega;
- salvestatud manused;
- hiljem SQLite andmebaasi `invoices` tabeli read.

Skaneerimise mõte on leida e-kirjad, millel on arve tunnuseid. Iga kiri saab skoori 0-100.

### 2.2 Brauseri kasutajaliides

Moodul:

- `web_app.py`

Vaated:

- `Koondlist`
- `Meriti list`
- `Maili list`
- `Projektita Meriti arved`
- `Pank vs Merit`
- `Laadi arve fail`
- `Laadi panga väljavõte`
- `Seadistus`
- `Märgi pangamaksed Meritis makstuks`

Kasutajaliidese ülesanne on mitte teha maksuarvestust pimesi, vaid näidata kasutajale andmed kontrollitavalt ja parandatavalt.

### 2.3 Andmebaas

Moodul:

- `invoice_db.py`

Andmebaas:

- SQLite fail, praegu tüüpiliselt `invoice_scan_with_files_test/ui_register.sqlite`.

Põhitabelid:

- `invoices`
- `invoice_events`
- `bank_transactions`
- `bank_import_events`
- `merit_external_payments`
- `app_settings`

### 2.4 Arvefailide lugemine

Moodulid:

- `invoice_extract.py`
- `pdf_text.py`
- `invoice_project_lines.py`

Toetatud allikad:

- PDF;
- XML/e-arve;
- käsitsi üles laaditud PDF;
- maili manused.

Loetavad väljad:

- arve number;
- arve kuupäev;
- tarnija;
- tarnija registrikood;
- KMKR;
- summa kokku;
- käibemaks;
- maksetähtaeg;
- IBAN/makse rekvisiidid;
- valuuta;
- projektiviited;
- arveread projektide kaupa, kui PDF tekst seda võimaldab.

### 2.5 Pangaväljavõtte import

Moodulid:

- `bank_import.py`
- `reconcile_bank.py`

Sisend:

- ISO XML 052 ehk camt.052 tüüpi Swedbanki väljavõte.

Väljund:

- `bank_transactions` tabel;
- import sündmus `bank_import_events`;
- arvetega sobitatud maksed;
- pangakanded, mille kohta dokument puudub.

### 2.6 Meriti integratsioon

Moodulid:

- `merit_api_client.py`
- `merit_api_payload.py`
- `merit_import.py`
- `web_app.py`

Meriti API funktsioonid:

- ostuarvete päring `getpurchorders`;
- ostuarve saatmine `sendpurchinvoice`;
- ostuarve makse saatmine `sendPaymentV`;
- tarnijate päring `getvendors`;
- pankade päring `getbanks`;
- makseviiside päring `getpaymenttypes`;
- dimensioonide/projektide päring `getdimensions`;
- dimensiooni väärtuste lisamine `senddimvalues`.

## 3. Andmebaasi loogika

### 3.1 `invoices`

Üks rida tähistab ühte arvekandidaati või kinnitatud arvet.

Olulisemad väljad:

- `fingerprint`: unikaalne tunnus, et sama arve ei dubleeruks;
- `status`: `pending`, `confirmed`, `rejected`;
- `invoice_kind`: `purchase_candidate` või `own_sales_invoice`;
- `invoice_number`;
- `invoice_date`;
- `issuer_name`;
- `issuer_email`;
- `payment_details`;
- `amount_total`;
- `vat_amount`;
- `due_date`;
- `issuer_reg_code`;
- `issuer_vat_no`;
- `currency`;
- `attachment_names`;
- `attachment_paths`;
- `archive_paths`;
- `import_source`: näiteks `mail_scan` või käsitsi upload;
- `extraction_status`;
- `payment_status`: `unknown`, `paid`, `unmatched` jne;
- `paid_amount`;
- `paid_date`;
- `bank_match_note`;
- `merit_status`: `not_sent`, `sent` jne;
- `merit_sent_at`;
- `merit_response`;
- `merit_error`;
- `merit_payment_sent_at`;
- `merit_payment_response`;
- `merit_payment_error`;
- `seen_count`.

### 3.2 `bank_transactions`

Üks rida tähistab ühte pangakannet.

Olulisemad väljad:

- `fingerprint`: unikaalne tunnus duplikaatide vältimiseks;
- `booking_date`;
- `value_date`;
- `credit_debit`: `DBIT` väljaminek, `CRDT` laekumine;
- `amount`;
- `currency`;
- `party_name`;
- `party_iban`;
- `remittance`;
- `entry_ref`;
- `bank_tx_code`;
- `account_iban`;
- `source_file`;
- `seen_count`.

Pangaväljavõtte korduv import ei tohiks samu kandeid topelt lisada. Kui fingerprint on sama, suurendatakse `seen_count` ja uuendatakse `last_seen_at`.

### 3.3 `merit_external_payments`

Kasutatakse nende maksete jälgimiseks, mis ei tulene otseselt kohalikust `invoices` reast või mis on saadetud pangakande põhjal.

Väljad:

- `candidate_key`;
- `source_type`;
- `source_id`;
- `invoice_number`;
- `supplier`;
- `amount`;
- `currency`;
- `paid_date`;
- `sent_at`;
- `response`;
- `error`.

### 3.4 `app_settings`

Seadistused:

- Meriti API ID;
- Meriti API võti;
- makse debitoor IBAN;
- vaikimisi käibemaks;
- vaikimisi artikkel;
- vaikimisi kulukonto;
- makseviis;
- projekti dimensiooni ID.

## 4. Arvekandidaadi leidmine e-kirjast

Moodul: `detection.py`

Iga kiri saab skoori.

Skoori komponendid:

- arvesõnad: kuni 45 punkti;
- tšeki või maksesõnad: kuni 25 punkti;
- arvelaadsed manused: 25 punkti;
- arve/tšeki nimega pildimanused: 15 punkti;
- võimalik arvenumber tekstis: 15 punkti;
- võimalik EUR summa tekstis: 10 punkti;
- negatiivsed sõnad nagu newsletter, reklaam, campaign: -25 punkti.

Arvesõnad:

- `arve`;
- `invoice`;
- `faktuur`;
- `bill`;
- `rechnung`;
- `ostuarve`;
- `müügiarve`;
- `käibemaks`;
- `km`.

Arvelaadsed faililaiendid:

- `.pdf`;
- `.xml`;
- `.asice`;
- `.bdoc`;
- `.ddoc`;
- `.xlsx`;
- `.xls`;
- `.csv`.

Pildid loetakse tugevamaks ainult siis, kui failinimes on näiteks `arve`, `invoice`, `receipt`, `tsekk`.

## 5. Ostuarve vs ERLINi müügiarve

Süsteemi eesmärk on importida ostuarveid.

Kui arve väljastaja on ERLIN OÜ või arve on selgelt ERLINi enda väljastatud müügiarve, peab see minema eraldi loogikasse `own_sales_invoice`, mitte tavalisse ostuarvete importi.

Oluline:

- ERLINi müügiarved võivad Outlookis olla, aga neid ei pea ostuarvetena Meritisse importima;
- müügiarved on Meritis/raamatupidamisprogrammis juba olemas;
- koondvaates peab olema võimalik neid filtreerida.

## 6. Arve PDF/XML info lugemine

Moodul: `invoice_extract.py`

### 6.1 XML

Kui fail on e-arve XML, kasutatakse XML struktuuri.

Väljad:

- arve nr;
- kuupäev;
- tarnija;
- registrikood;
- KMKR;
- summa;
- KM;
- maksetähtaeg;
- IBAN;
- valuuta.

XML on eelistatud allikas, sest see on struktureeritud.

### 6.2 PDF

PDF-ist loetakse tekst ja kasutatakse regulaaravaldisi/heuristikaid.

Loogika:

- otsitakse arvenumbri märgendeid;
- otsitakse kuupäevi;
- otsitakse summasid;
- otsitakse KM ridu;
- otsitakse IBAN formaati;
- otsitakse registrikoodi ja KMKR tunnuseid;
- tarnija tuvastamisel välditakse kliendi nime lugemist tarnijaks;
- brutot/netot kontrollitakse valemiga neto + KM = bruto.

Kui PDF-is on `summa kokku`, `tasuda`, `kokku EUR` jne, eelistatakse neid ridu. Kui võimalik summa on tegelikult neto, kontrollitakse, kas neto + KM = arve kokku.

### 6.3 Projektiviited arveridadelt

Moodul: `invoice_project_lines.py`

Projektiviide:

- 5-kohaline number;
- algab tavaliselt `25` või `26`;
- esimesed kaks numbrit viitavad aastale;
- viimased kolm on aasta sees jooksev number.

Oluline erireegel:

- kui real on näiteks `26000 - ... / 26070`, võetakse projektiks `26000`, mitte `26070`.
- põhjus: `26000` on eelarvestuse projekt; `26070` on informatiivne hilisem võimalik tööprojekt.

Meritisse saatmisel peab arvereal olema:

- artikkel: näiteks `alltöö`;
- konto: näiteks `4009 - Alltöövõtutööd`;
- kirjeldus: võimalikult kogu arverea kirjeldus, näiteks `AKT 05-32 Erlin OÜ - (25214 - Lennujaama laiendus / Marion)`;
- projekt: realt tuvastatud projektiviide.

Kui projekt puudub Meritis, peab süsteem enne arve saatmist kontrollima Meriti dimensioone ja vajadusel looma puuduva projekti.

## 7. Pangaväljavõtte import

Moodul: `bank_import.py`

Sisend on ISO XML 052.

Iga kanne salvestatakse tabelisse `bank_transactions`.

Olulised väljad:

- kuupäev;
- summa;
- valuuta;
- debet/krediit;
- vastaspoole nimi;
- vastaspoole IBAN;
- selgitus;
- viitenumber või entry ref;
- konto IBAN.

Import on idempotentne: sama pangakande uuesti importimine ei tekita uut rida.

## 8. Arve ja pangakande sobitamine

Moodul: `reconcile_bank.py`

Sobituse skoor `invoice_match_score`:

- summa klapib kuni 0.01 täpsusega: +50;
- IBAN klapib: +35;
- arve number on panga selgituses: +45;
- muu token kattub: +35;
- vastaspoole nimi klapib tarnijaga lihtsa sisaldumise alusel: +20.

Kui parim skoor on vähemalt 50, loetakse vaste leitud.

Debetkanne (`DBIT`) sobitatakse ostuarvega.

Krediitkanne (`CRDT`) sobitatakse müügiarvega.

Kui pangakanne sobib arvega:

- `invoices.payment_status = paid`;
- `paid_amount = bank.amount`;
- `paid_date = bank.booking_date`;
- `bank_match_note` sisaldab skoori ja põhjuseid.

Kui debetkanne ei leia arvet:

- see ilmub kui võimalik puuduv ostudokument.

Kui arve ei leia pangakannet:

- see jääb maksmata või kontrollimata staatusesse.

## 9. Meriti ostuarved vs pangakanded

Moodulid:

- `compare_merit_bank_mail.py`
- `web_app.py`

Vaade:

- `Pank vs Merit`

Selles funktsioonis kasutatakse Meriti API live andmeid, mitte ainult kohalikku andmebaasi.

Pangakanded tulevad kohalikust `bank_transactions` tabelist.

Meriti arved tulevad API kaudu `getpurchorders` päringust.

### 9.1 Meriti arve ja pangakande skoor

Funktsioon: `match_score_merit_bank`

Skoor:

- summa klapib kuni 0.01: +50;
- arve number on pangaselgituses: +45;
- muu arve/token kattub: +35;
- tarnija ja pangapoole nimi klapivad: +30.

Tarnija nime normaliseerimisel ignoreeritakse ettevõtte vorme:

- `AS`;
- `Aktsiaselts`;
- `OÜ`;
- `Osaühing`;
- `MTÜ`;
- `FIE`;
- `SA`;
- `OY`.

Näide:

- Meritis: `Aktsiaselts Esvika Elekter`;
- pangas: `AS ESVIKA ELEKTER`;
- loetakse samaks nimeks.

`Pank vs Merit` vaates aktsepteeritakse pangavaste tavaliselt siis, kui skoor on vähemalt 80.

### 9.2 Perioodiloogika

Pank vs Merit periood piirab pangakandeid.

Meriti arveid küsitakse vajadusel laiemalt, sest arve võib olla varasemast kuust, aga makse valitud perioodis.

Näide:

- Meriti arve kuupäev: 2026-04-27;
- pangamakse: 2026-06-01;
- kui vaade on `Jooksev kuu`, peab juunikuu makse leidma ka aprilli Meriti arve.

## 10. Koondlist

Vaade: `Koondlist`

Koondlist ühendab kolm allikat:

- Meriti arved;
- mailist/käsitsi leitud arved;
- pangakanded.

Veerud näitavad:

- kas arve on Meritis;
- kas arve on mailis/käsitsi registris;
- kas arve on pangas;
- Meriti makse staatus;
- panga makse staatus;
- panga vaste info;
- allikas.

Pangaread loetakse otse SQLite `bank_transactions` tabelist, mitte vanast CSV-st.

Kui pangakanne klapib olemasoleva Meriti/maili reaga summa ja tarnija järgi, liidetakse see samasse ritta.

Kui pangakanne ei klapi ühegi arvega, ilmub see eraldi `Pank` allika reana.

## 11. Meriti ostuarve saatmine

Moodulid:

- `merit_api_payload.py`
- `web_app.py`

Funktsioon:

- `send_invoice_to_merit`

Enne saatmist:

- kasutaja peab arve kinnitama;
- arvel peavad olema põhiandmed;
- kontrollitakse, kas arve pole juba saadetud;
- projektiread analüüsitakse;
- vajadusel kontrollitakse ja luuakse Meritisse puuduvad projektid.

Payload sisaldab:

- tarnija;
- arve number;
- kuupäev;
- maksetähtaeg;
- valuuta;
- read;
- artikkel;
- konto;
- käibemaks;
- projektid/dimensioonid;
- manus PDF kujul, kui olemas.

Kui arve on pangas juba makstud, võib tulevikus saata ka makse info, kuid praeguses loogikas on makstuks märkimine eraldi funktsioon.

## 12. Pangas makstud arvete Meritisse makstuks märkimine

Vaade:

- `Märgi pangamaksed Meritis makstuks`

Eesmärk:

- leida arved, mis on meie andmebaasi järgi pangas makstud;
- mille arve on Meritisse saadetud;
- mille kohta meie lokaalne süsteem ei tea, et makse oleks Meritisse saadetud;
- kontrollida alles siis Meriti live andmetest, kas arve on tegelikult juba makstud;
- pakkuda saatmiseks ainult neid, mis Meriti live info järgi on tasumata.

### 12.1 Kohalik eelkontroll

Kohalik kandidaat peab vastama tingimustele:

- `invoice_kind = purchase_candidate`;
- `merit_status = sent`;
- `payment_status = paid`;
- `paid_amount` olemas;
- `paid_date` olemas;
- `merit_payment_sent_at` tühi;
- `merit_payment_error` ei sisalda Meriti teadet, et tasumata ostuarvet pole.

Valitud periood piirab `paid_date` välja.

### 12.2 Live kontroll

Iga kohaliku kandidaadi kohta:

- küsitakse Meritist ainult selle kandidaadi arve kuupäeva/makse kuupäeva ümbruse ostuarved;
- otsitakse arvet numbri ja summa järgi;
- kui Meritist ei leita, tulemus `Ei saada`;
- kui Merit ütleb `paid` või `partially_paid`, tulemus `Ei saada`;
- kui Merit ütleb `unpaid`, tulemus `Saadetav`;
- kui summa ei klapi, tulemus `Vajab kontrolli`.

### 12.3 Live logi

Sellel lehel kasutatakse SSE stream endpointi:

- `/api/merit/payment-preview-stream`

Brauserisse ilmub iga kontrollitud rida kohe.

Logi veerud:

- kuupäev;
- tarnija;
- arve nr;
- arve summa;
- kohalik pank;
- kohalik Merit;
- Meriti live;
- result;
- selgitus.

Näited:

- `Kontrollin` - Meriti live päring on käimas;
- `Ei saada` - Meriti live järgi juba makstud või arvet ei leitud;
- `Saadetav` - Meriti live järgi tasumata ja saab märkida makstuks;
- `Vajab kontrolli` - summa või muu andmeosa vajab kasutaja otsust.

### 12.4 Maksmise saatmine Meritisse

Funktsioon:

- `send_merit_payments`

Payload `sendPaymentV` jaoks:

- `BankId`;
- `IBAN`;
- `VendorName`;
- `PaymentDate`;
- `BillNo`;
- `RefNo`;
- `Amount`;
- vajadusel `CurrencyCode`.

Kui Merit vastab, et selliste parameetritega tasumata ostuarvet pole, tõlgendab süsteem seda nii, et arve on Meritis juba makstud või ei ole enam tasumata. Sel juhul märgitakse lokaalselt tulemus vastavalt, et sama rida lõputult uuesti ei pakutaks.

## 13. Meriti projektita arved

Vaade:

- `Projektita Meriti arved`

Loogika:

- Meriti ostuarved küsitakse API-st;
- leitakse projektidimensiooni väli;
- kui arvel puudub projekti väärtus, näidatakse rida kasutajale.

Eesmärk:

- leida Meritis olevad ostuarved, millele pole projekt määratud.

## 14. Käsitsi arve üleslaadimine

Vaade:

- `Laadi arve fail`

Loogika:

- kasutaja valib PDF/XML faili;
- fail salvestatakse rakenduse juurde;
- arve loetakse `invoice_extract.py` abil;
- rida lisatakse `invoices` tabelisse;
- `import_source` eristab käsitsi lisatud arved mailiskännist.

Käsitsi üles laaditud arve peab ilmuma koondlisti ja seda saab hiljem Meritisse saata.

## 15. Arvete arhiveerimine kaustadesse

Kui arve kinnitatakse, on planeeritud/olemas loogika, et fail salvestatakse kaustadesse:

- aasta;
- kuu.

Eesmärk:

- kinnitatud arved on failisüsteemis korrastatud;
- hilisem EMTA/XML/Merit töövoog saab kasutada kinnitatud failide kogumit.

## 16. SEPA maksefail

Moodul:

- `sepa_payment.py`

Eesmärk:

- koostada maksefail, mille saab panka importida.

Väljad:

- maksja nimi;
- maksja IBAN;
- saaja;
- saaja IBAN;
- summa;
- valuuta;
- selgitus;
- makse kuupäev.

Swedbanki API integratsiooni veel ei ole. Praegune turvalisem suund on fail või maksekorralduse ettevalmistus, kus kinnitamine jääb panka PIN/Smart-ID/Mobiil-ID abil.

## 17. EMTA ekspordi tulevane loogika

Plaanitav funktsioon:

- kinnitatud ostuarved;
- Meritis olemasolevad arved;
- pangas makstud/maksmata info;
- KMD/KMD INF ekspordiks sobiv koond.

Oluline:

- KMD INF puhul tuleb arvestada tehingupartneri põhist 1000 euro piirmäära;
- müügi- ja ostuarved on eraldi;
- eksport peab olema enne üleslaadimist kasutaja poolt kontrollitav.

Soovitatav töövoog:

1. PST/käsitsi failid -> arved andmebaasi.
2. Kasutaja kinnitab ostuarved.
3. Pank imporditakse.
4. Merit võrdlus.
5. Puuduvad arved saadetakse Meritisse.
6. Pangas makstud arved märgitakse Meritis makstuks.
7. EMTA KMD/KMD INF ekspordi eelvaade.
8. Kasutaja kinnitab.
9. XML/CSV eksporditakse.

## 18. Olulised riskid ja piirangud

### 18.1 PDF ei ole usaldusväärne andmeallikas

PDF-id on eri kujundusega. Sama väli võib olla:

- tekstina;
- pildina;
- tabelis;
- mitmel real;
- kliendi, mitte tarnija plokis.

Seetõttu peab kasutajaliides alati lubama käsitsi parandamist.

### 18.2 Sama arve võib tulla mitmest allikast

Allikad:

- mail;
- käsitsi upload;
- Merit;
- pank.

Duplikaatide vältimiseks kasutatakse:

- fingerprint;
- arve nr + summa;
- tarnija nimi;
- pangaselgitus;
- failinimed.

### 18.3 Tarnijanimed erinevad

Näited:

- `AS ESVIKA ELEKTER`;
- `Aktsiaselts Esvika Elekter`;
- `Esvika Elekter AS`.

Selleks kasutatakse normaliseerimist ja ettevõtte vormisõnade ignoreerimist.

### 18.4 Perioodid on keerulised

Arve kuupäev ja makse kuupäev võivad olla eri kuudes.

Vaadetes peab olema selge, kas periood piirab:

- arve kuupäeva;
- pangamakse kuupäeva;
- Meriti kande kuupäeva.

Praegune suund:

- `Pank vs Merit`: periood piirab panka, Meriti arveid küsitakse laiemalt;
- `Märgi pangamaksed Meritis makstuks`: periood piirab pangas maksmise kuupäeva.

### 18.5 Meriti API vastused võivad olla aeglased või puudulikud

Seetõttu:

- enne API kasutamist tehakse kohalik eelfilter;
- live logi peab näitama, millise rea juures kontroll on;
- kasutajale ei tohi jääda muljet, et süsteem hangus.

## 19. Kui tarkvara nullist uuesti kirjutada

Minimaalne uus arhitektuur:

### Backend

- Python FastAPI või Django;
- SQLite arenduses, PostgreSQL tootmises;
- eraldi taustatööd pikkade importide jaoks;
- API endpointid:
  - `/invoices`;
  - `/bank/import`;
  - `/bank/reconcile`;
  - `/merit/settings`;
  - `/merit/purchase-invoices`;
  - `/merit/send-invoice`;
  - `/merit/payment-preview-stream`;
  - `/merit/send-payments`;
  - `/emta/export-preview`;
  - `/emta/export`.

### Frontend

- React/Vue/Svelte või lihtne server-renderdatud UI;
- tabelid filtrite ja sortimisega;
- live logi pikkade operatsioonide jaoks;
- detailpaneel arve parandamiseks;
- selge eristus: Meritis / Mailis / Pangas / Käsitsi.

### Andmekiht

Põhiobjektid:

- Invoice;
- InvoiceFile;
- BankTransaction;
- MeritInvoiceSnapshot;
- ReconciliationResult;
- PaymentCandidate;
- ExportBatch;

### Reeglimootor

Eraldi moodulid:

- invoice extraction;
- bank matching;
- Merit matching;
- duplicate detection;
- project parsing;
- tax/VAT validation;
- EMTA export validation.

Kõik skoorid ja lävendid võiksid olla konfiguratsioonis, mitte koodi sisse kõvasti kirjutatud.

## 20. Praegused kõige olulisemad skoorilävendid

Arvekandidaat e-kirjast:

- 0-100, min_score sõltub skänni seadistusest.

Pangakanne vs kohalik arve:

- aktsepteeritakse alates 50.

Meriti arve vs pangakanne:

- üldine `best_match` aktsepteerib alates 50;
- `Pank vs Merit` vaates kasutatakse tugevamat lävendit 80.

Summa võrreldakse:

- täpsusega 0.01.

Arve number:

- tugev vaste, kui arve number esineb pangaselgituses.

Nimi:

- nõrgem/täiendav vaste;
- ettevõtte vormid normaliseeritakse.

## 21. Failid ja moodulite vastutus

- `web_app.py`: brauseri UI, HTTP API, koondloogika, Meriti operatsioonide orchestration.
- `invoice_db.py`: SQLite skeem, migratsioonid, andmebaasi abifunktsioonid.
- `detection.py`: e-kirja arvekandidaadi skoorimine.
- `pst_reader.py`: PST lugemine.
- `invoice_extract.py`: PDF/XML arve väljade tuvastus.
- `invoice_project_lines.py`: projektiviidete ja arveridade lugemine.
- `bank_import.py`: ISO XML 052 pangaväljavõtte import.
- `reconcile_bank.py`: panga ja kohalike arvete sobitus.
- `compare_merit_bank_mail.py`: Meriti, panga ja maili võrdluse skoorid.
- `merit_api_client.py`: Meriti API madaltaseme klient.
- `merit_api_payload.py`: ostuarve payloadi koostamine.
- `merit_import.py`: Meriti Excel/CSV impordi varasem abiloogika.
- `sepa_payment.py`: SEPA maksefail.
- `archive_confirmed.py`: kinnitatud arvete arhiveerimine.

## 22. Kontrollitavad testid

Praegused testid katavad:

- e-kirjade tuvastust;
- PDF/XML väljade lugemist;
- projektiridade lugemist;
- Merit API payloadi;
- SEPA maksefaili;
- Meriti ja panga nime/summa sobituse erijuhte.

Testide käivitamine:

```powershell
$env:PYTHONPATH='...\outputs\pst_invoice_finder'
python -m unittest discover -s outputs\pst_invoice_finder\tests
```

Praegune seis: 18 testi.

