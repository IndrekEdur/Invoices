import unittest
from decimal import Decimal

from pst_invoice_finder.invoice_project_lines import parse_project_lines_from_text
from pst_invoice_finder.merit_api_payload import build_invoice_rows


class InvoiceProjectLineTests(unittest.TestCase):
    def test_extracts_project_lines_from_konekto_style_pdf_text(self) -> None:
        text = """
        AKT 05-32 Erlin OÜ - (25200 - Iseära ridaleamud IV etapp / Marion) 6 20,00 120,00
        AKT 05-32 Erlin OÜ - (26000 - Raadi Hesburger ja Jazz / 26070
        Marion)
        8 20,00 160,00
        """

        rows = parse_project_lines_from_text(text)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].project_code, "25200")
        self.assertEqual(rows[0].project_name, "Iseära ridaleamud IV etapp")
        self.assertEqual(rows[0].description, "AKT 05-32 Erlin OÜ - (25200 - Iseära ridaleamud IV etapp / Marion)")
        self.assertEqual(rows[0].quantity, Decimal("6"))
        self.assertEqual(rows[0].unit_price, Decimal("20.00"))
        self.assertEqual(rows[0].net_amount, Decimal("120.00"))
        self.assertEqual(rows[1].project_code, "26000")
        self.assertEqual(rows[1].project_name, "Raadi Hesburger ja Jazz")
        self.assertEqual(rows[1].description, "AKT 05-32 Erlin OÜ - (26000 - Raadi Hesburger ja Jazz / 26070 Marion)")

    def test_builds_merit_rows_with_dimensions(self) -> None:
        project_lines = parse_project_lines_from_text(
            "AKT 05-32 Erlin OÜ - (25217 - Taltech Raamatukogu / Marion) 38 20,00 760,00"
        )

        rows = build_invoice_rows(
            {"subject": "KONEKTO arve"},
            project_lines=project_lines,
            item_code="alltöö",
            tax_id="tax-guid",
            gl_account_code="4009",
            fallback_net=Decimal("760.00"),
            project_dimension_id=5,
            project_values={"25217": {"Id": "project-guid"}},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Quantity"], 38.0)
        self.assertEqual(rows[0]["Price"], 20.0)
        self.assertEqual(rows[0]["Item"]["Code"], "alltöö")
        self.assertEqual(rows[0]["Item"]["Description"], "AKT 05-32 Erlin OÜ - (25217 - Taltech Raamatukogu / Marion)")
        self.assertEqual(rows[0]["Description"], "AKT 05-32 Erlin OÜ - (25217 - Taltech Raamatukogu / Marion)")
        self.assertEqual(rows[0]["GLAccountCode"], "4009")
        self.assertEqual(rows[0]["Dimensions"][0]["DimId"], 5)
        self.assertEqual(rows[0]["Dimensions"][0]["DimCode"], "25217")
        self.assertEqual(rows[0]["Dimensions"][0]["DimValueId"], "project-guid")

    def test_extracts_single_project_reference_from_teemu_comment(self) -> None:
        project_lines = parse_project_lines_from_text(
            "Kommentaar: Objekti viide arvel 26078-Veskiposti 8 Lk 1 / 1"
        )

        self.assertEqual(len(project_lines), 1)
        self.assertEqual(project_lines[0].project_code, "26078")
        self.assertEqual(project_lines[0].project_name, "Veskiposti 8")
        self.assertEqual(project_lines[0].quantity, Decimal("1"))
        self.assertEqual(project_lines[0].net_amount, Decimal("0"))

    def test_single_project_reference_uses_invoice_net_as_row_price(self) -> None:
        project_lines = parse_project_lines_from_text(
            "Kommentaar: Objekti viide arvel 26078-Veskiposti 8 Lk 1 / 1"
        )

        rows = build_invoice_rows(
            {"subject": "TEEMU arve"},
            project_lines=project_lines,
            item_code="alltöö",
            tax_id="tax-guid",
            gl_account_code="4009",
            fallback_net=Decimal("100.47"),
            project_dimension_id=5,
            project_values={"26078": {"Id": "project-guid"}},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Quantity"], 1.0)
        self.assertEqual(rows[0]["Price"], 100.47)
        self.assertEqual(rows[0]["Dimensions"][0]["DimCode"], "26078")


if __name__ == "__main__":
    unittest.main()
