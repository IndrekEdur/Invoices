import unittest
from pathlib import Path

from pst_invoice_finder.invoice_extract import extract_from_text, pick_invoice_number_from_filename


class InvoiceExtractTests(unittest.TestCase):
    def test_extracts_common_invoice_fields_from_text(self) -> None:
        text = """
        Arve kuupäev: 26.03.2026
        Maksetähtaeg: 02.04.2026
        Registrikood: 12345678
        KMKR: EE123456789
        IBAN EE121010220034567890
        Käibemaks 24% 24,00
        Kokku tasuda 124,00 EUR
        """

        fields = extract_from_text(text)

        self.assertEqual(fields.invoice_date, "2026-03-26")
        self.assertEqual(fields.due_date, "2026-04-02")
        self.assertEqual(fields.issuer_reg_code, "12345678")
        self.assertEqual(fields.issuer_vat_no, "EE123456789")
        self.assertEqual(fields.payment_details, "EE121010220034567890")
        self.assertEqual(fields.vat_amount, "24.00")
        self.assertEqual(fields.amount_total, "124.00")
        self.assertEqual(fields.extraction_status, "ok")

    def test_extracts_esvika_style_footer_fields(self) -> None:
        text = """
        Tähtaeg 01.06.2026
        Vahesumma 4,52
        KM summa 1,08
        Kokku € (KM-ga) 5,60
        Arve on makstud.
        Esvika Elekter AS Registreerimisnr.: 10166316 Müügiesindused
        Karjavälja tn 6 KMKR: EE100427897
        IBAN: EE842200221001157980
        """

        fields = extract_from_text(text)

        self.assertEqual(fields.issuer_name, "Esvika Elekter AS")
        self.assertEqual(fields.issuer_reg_code, "10166316")
        self.assertEqual(fields.issuer_vat_no, "EE100427897")
        self.assertEqual(fields.payment_details, "EE842200221001157980")
        self.assertEqual(fields.vat_amount, "1.08")
        self.assertEqual(fields.amount_total, "5.60")
        self.assertEqual(fields.due_date, "2026-06-01")

    def test_skips_erlin_buyer_when_supplier_is_in_footer(self) -> None:
        text = """
        Arve MA0031745
        Dokumendi 15.06.2026 Tellimuse nr. MT0045078
        Tahtaeg 15.06.2026
        Erlin OU
        Reg. nr. 12272502
        EE101658885
        Vahesumma 35,92
        KM summa 8,62
        Kokku EUR (KM-ga) 44,54
        Esvika Elekter AS Registreerimisnr.: 10166316 Muugiesindused
        Karjavalja tn 6 KMKR: EE100427897
        IBAN: EE842200221001157980
        """

        fields = extract_from_text(text)

        self.assertEqual(fields.issuer_name, "Esvika Elekter AS")
        self.assertEqual(fields.invoice_number, "MA0031745")
        self.assertEqual(fields.issuer_reg_code, "10166316")
        self.assertEqual(fields.issuer_vat_no, "EE100427897")
        self.assertEqual(fields.payment_details, "EE842200221001157980")
        self.assertEqual(fields.amount_total, "44.54")
        self.assertEqual(fields.vat_amount, "8.62")

    def test_extracts_amb_project_invoice_fields(self) -> None:
        text = """
        Klient: Arve nr.: 202603-07
        Erlin OÜ Kuupäev: 31.03.2026
        Tähtaeg: 21.04.2026
        Summa ilma km-ta 197,18
        KM (24%) 47,32
        Summa Kokku 244,50
        AMB PROJEKT OÜ Pank: Swedbank
        Reg.nr 14230070 SWIFT: HABAEE2X
        Sagari tn 4, Tallinn 13522 Estonia IBAN: EE742200221066256897
        info@ambprojekt.eu +372 56452370 VAT no.: EE101968449
        """

        fields = extract_from_text(text)

        self.assertEqual(fields.invoice_number, "202603-07")
        self.assertEqual(fields.invoice_date, "2026-03-31")
        self.assertEqual(fields.due_date, "2026-04-21")
        self.assertEqual(fields.issuer_name, "AMB PROJEKT OÜ")
        self.assertEqual(fields.issuer_reg_code, "14230070")
        self.assertEqual(fields.issuer_vat_no, "EE101968449")
        self.assertEqual(fields.payment_details, "EE742200221066256897")
        self.assertEqual(fields.vat_amount, "47.32")
        self.assertEqual(fields.amount_total, "244.50")

    def test_extracts_alter_baltics_invoice_fields(self) -> None:
        text = """
        ARVE-SAATELEHT nr. 2603489 12.06.2026
        Alter Baltics OÜ Tel: +372 651 9666 Reg Nr: 12026341
        Ämma tee 70, Iru küla, Jõelähtme
        Faks: KMKR nr: EE101414168
        SEB PANK AS SWIFT: EEUHEE2X IBAN:EE371010220123184220
        Saaja: Erlin OÜ
        Tähtaeg: 12.07.2026
        Maksumus käibemaksuta EUR 2 256.00
        Käibemaks 24 % 541.44
        KOKKU EUR 2 797.44
        """

        fields = extract_from_text(text)

        self.assertEqual(fields.invoice_number, "2603489")
        self.assertEqual(fields.invoice_date, "2026-06-12")
        self.assertEqual(fields.due_date, "2026-07-12")
        self.assertEqual(fields.issuer_name, "Alter Baltics OÜ")
        self.assertEqual(fields.issuer_reg_code, "12026341")
        self.assertEqual(fields.issuer_vat_no, "EE101414168")
        self.assertEqual(fields.payment_details, "EE371010220123184220")
        self.assertEqual(fields.vat_amount, "541.44")
        self.assertEqual(fields.amount_total, "2797.44")

    def test_extracts_teemu_invoice_number_without_nr_label(self) -> None:
        text = """
        Klient: Erlin OÜ ARVE-SAATELEHT 22604323
        Õunapuu pst 8 Kuupäev: 26.06.2026
        Tasumistähtaeg: 26.06.2026
        KMKR nr: EE101658885
        Arve väljastas: Oliver Brus Kokku EUR 100.47
        Käibemaks 24%: EUR: 24.11
        Tasuda EUR: 0.00
        Sisaldab ettemaksu EUR: 124.58
        Teemu-E OÜ Telefon: 53358235 Pank: Swedbank AS
        Gaasi 4a email: teemu@teemu.ee IBAN: EE282200221001159182
        Reg nr: 10420068
        KMKR nr: EE100203008
        """

        fields = extract_from_text(text)

        self.assertEqual(fields.invoice_number, "22604323")
        self.assertEqual(fields.invoice_date, "2026-06-26")
        self.assertEqual(fields.due_date, "2026-06-26")
        self.assertEqual(fields.issuer_name, "Teemu-E OÜ")
        self.assertEqual(fields.issuer_reg_code, "10420068")
        self.assertEqual(fields.issuer_vat_no, "EE100203008")
        self.assertEqual(fields.amount_total, "124.58")
        self.assertEqual(fields.vat_amount, "24.11")

    def test_extracts_foreign_ovoko_invoice_fields(self) -> None:
        text = """
        VAT Invoice
        Invoice series: OVO No.: 24027
        2026-06-24
        Seller Buyer
        Autocirc Rewinner AB Indrek Edur
        Kallebackens vag 1, Sollebrunn Karuslase tanav 7-1 Tallinn, 11913, Estonia
        Sweden Estonia
        Reg. No.: 5591440952 Reg. No.:
        VAT No.: SE559144095201 VAT No.:
        IBAN: SE5891900000091959080026 Phone: +3725214401
        VAT 24%: 23.51 EUR
        Total with VAT: 121.46 EUR
        """

        fields = extract_from_text(text)

        self.assertEqual(fields.invoice_number, "OVO24027")
        self.assertEqual(fields.invoice_date, "2026-06-24")
        self.assertEqual(fields.issuer_name, "Autocirc Rewinner AB")
        self.assertEqual(fields.issuer_reg_code, "5591440952")
        self.assertEqual(fields.issuer_vat_no, "SE559144095201")
        self.assertEqual(fields.payment_details, "SE5891900000091959080026")
        self.assertEqual(fields.amount_total, "121.46")
        self.assertEqual(fields.vat_amount, "23.51")

    def test_uses_filename_number_only_when_it_exists_in_text(self) -> None:
        text = "Tellimus kinnitatud. Dokumendi viide 22604323."

        invoice_number = pick_invoice_number_from_filename(Path("Arve_22604323 teemu.pdf"), text)

        self.assertEqual(invoice_number, "22604323")
        self.assertEqual(pick_invoice_number_from_filename(Path("Arve_99999999 teemu.pdf"), text), "")


if __name__ == "__main__":
    unittest.main()
