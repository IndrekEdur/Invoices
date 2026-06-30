# PST Invoice Finder MVP

## Architecture Documents

`ENTERPRISE_DOMAIN_MAP.md` describes the business domain vision: what the organization should know, remember, communicate, and act on.

`COMMUNICATION_ARCHITECTURE.md` describes how business communication, especially e-mails, becomes part of organization memory.

`PROJECT_ARCHITECTURE.md` describes Project as the primary business context connecting people, documents, communication, workflows, accounting, and knowledge.

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
