import unittest

from pst_invoice_finder.compare_merit_bank_mail import match_score_merit_bank


class CompareMeritBankMailTests(unittest.TestCase):
    def test_company_type_words_do_not_break_bank_match(self):
        merit = {
            "supplier": "Aktsiaselts Esvika Elekter",
            "invoice_number": "MA0031745",
            "amount_total": "44.54",
            "description": "",
        }
        bank = {
            "credit_debit": "DBIT",
            "amount": "44.54",
            "party_name": "AS ESVIKA ELEKTER",
            "remittance": "Tellimuse kinnitus MT0045078",
        }

        score, reasons = match_score_merit_bank(merit, bank)

        self.assertGreaterEqual(score, 80)
        self.assertIn("amount", reasons)
        self.assertIn("party", reasons)


if __name__ == "__main__":
    unittest.main()
