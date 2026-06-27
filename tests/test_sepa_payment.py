import unittest
import xml.etree.ElementTree as ET
from datetime import date

from pst_invoice_finder.sepa_payment import build_sepa_payment_xml


class SepaPaymentTests(unittest.TestCase):
    def test_builds_single_invoice_payment_file(self) -> None:
        row = {
            "id": "17",
            "status": "confirmed",
            "invoice_kind": "purchase_candidate",
            "invoice_number": "Arve MA0028639",
            "issuer_name": "Esvika Elekter AS",
            "payment_details": "IBAN: EE842200221001157980",
            "amount_total": "5,60",
            "currency": "EUR",
            "due_date": "2026-06-25",
            "payment_status": "unknown",
        }

        payment_file = build_sepa_payment_xml(
            row,
            debtor_name="ERLIN OÜ",
            debtor_iban="EE382200221020145685",
            today=date(2026, 6, 20),
        )

        root = ET.fromstring(payment_file.xml)
        ns = {"p": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"}
        self.assertEqual(root.findtext(".//p:Dbtr/p:Nm", namespaces=ns), "ERLIN OÜ")
        self.assertEqual(root.findtext(".//p:DbtrAcct/p:Id/p:IBAN", namespaces=ns), "EE382200221020145685")
        self.assertEqual(root.findtext(".//p:Cdtr/p:Nm", namespaces=ns), "Esvika Elekter AS")
        self.assertEqual(root.findtext(".//p:CdtrAcct/p:Id/p:IBAN", namespaces=ns), "EE842200221001157980")
        self.assertEqual(root.findtext(".//p:InstdAmt", namespaces=ns), "5.60")
        self.assertEqual(root.findtext(".//p:ReqdExctnDt", namespaces=ns), "2026-06-25")
        self.assertEqual(root.findtext(".//p:Ustrd", namespaces=ns), "Arve MA0028639")
        self.assertTrue(payment_file.filename.endswith(".xml"))

    def test_requires_debtor_iban(self) -> None:
        row = {
            "id": "17",
            "status": "confirmed",
            "invoice_kind": "purchase_candidate",
            "invoice_number": "MA0028639",
            "issuer_name": "Esvika Elekter AS",
            "payment_details": "EE842200221001157980",
            "amount_total": "5.60",
            "currency": "EUR",
        }

        with self.assertRaises(ValueError):
            build_sepa_payment_xml(row, debtor_name="ERLIN OÜ", debtor_iban="")


if __name__ == "__main__":
    unittest.main()
