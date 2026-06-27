from datetime import datetime
import unittest

from pst_invoice_finder.detection import make_candidate, score_email
from pst_invoice_finder.models import AttachmentInfo, EmailInfo


class DetectionTests(unittest.TestCase):
    def test_invoice_email_scores_high(self) -> None:
        email = EmailInfo(
            folder="Root/Inbox",
            subject="Arve 2026-104",
            sender_name="Tarnija OÜ",
            sender_email="arved@example.com",
            sent_at=datetime(2026, 5, 12, 10, 0),
            body_preview="Tere, manusena arve summas 122,00 EUR.",
            attachments=[AttachmentInfo(filename="arve-2026-104.pdf")],
        )

        score, reasons = score_email(email)

        self.assertGreaterEqual(score, 70)
        self.assertTrue(reasons)
        self.assertIsNotNone(make_candidate(email, min_score=45))

    def test_newsletter_scores_low(self) -> None:
        email = EmailInfo(
            folder="Root/Inbox",
            subject="Juuni uudiskiri",
            sender_name="Marketing",
            sender_email="news@example.com",
            sent_at=None,
            body_preview="Newsletter campaign",
            attachments=[],
        )

        score, _ = score_email(email)

        self.assertLess(score, 45)
        self.assertIsNone(make_candidate(email, min_score=45))


if __name__ == "__main__":
    unittest.main()
