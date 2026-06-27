import unittest

from pst_invoice_finder.merit_api_payload import build_purchase_invoice_payload


class MeritApiPayloadTests(unittest.TestCase):
    def test_build_purchase_invoice_payload_without_attachment(self):
        row = {
            "invoice_number": "31314859",
            "invoice_date": "2026-03-26",
            "due_date": "2026-04-01",
            "issuer_name": "AS DECORA",
            "issuer_reg_code": "10000000",
            "issuer_vat_no": "EE100000000",
            "issuer_email": "arve@example.com",
            "amount_total": "1742.16",
            "vat_amount": "337.20",
            "currency": "EUR",
            "payment_details": "EE123456789",
            "paid_amount": "1742.16",
            "paid_date": "2026-03-31",
            "bank_match_note": "Bank row 1",
            "subject": "Decora arve 31314859",
            "attachment_paths": "",
        }

        preview = build_purchase_invoice_payload(row)
        payload = preview["payload"]

        self.assertTrue(preview["endpoint"].endswith("/api/v2/sendpurchinvoice"))
        self.assertEqual(payload["Vendor"]["Name"], "AS DECORA")
        self.assertEqual(payload["BillNo"], "31314859")
        self.assertEqual(payload["DocDate"], "20260326")
        self.assertEqual(payload["DueDate"], "20260401")
        self.assertEqual(payload["TotalAmount"], 1404.96)
        self.assertEqual(payload["TaxAmount"][0]["Amount"], 337.2)
        self.assertEqual(payload["InvoiceRow"][0]["Item"]["Code"], "alltöö")
        self.assertEqual(payload["InvoiceRow"][0]["GLAccountCode"], "4009")
        self.assertEqual(payload["Payment"]["PaidAmount"], 1742.16)
        self.assertEqual(payload["Payment"]["PaymDate"], "202603310000")
        self.assertNotIn("Attachment", payload)
