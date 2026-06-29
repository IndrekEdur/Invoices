from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.services import CreateOrganizationCommand, OrganizationService

from .models import Document, DocumentTag, DocumentVersion


def create_organization(name="Documents Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


class DocumentModelTests(TestCase):
    def test_can_create_document_linked_to_organization(self):
        organization = create_organization()

        document = Document.objects.create(
            organization=organization,
            title="Supplier invoice",
            original_filename="invoice.pdf",
            source=Document.Source.MANUAL_UPLOAD,
            mime_type="application/pdf",
            size_bytes=12345,
            sha256="a" * 64,
            metadata={"supplier": "Example OÜ"},
        )

        self.assertIsNotNone(document.id)
        self.assertIsNotNone(document.uuid)
        self.assertEqual(document.organization, organization)
        self.assertEqual(str(document), "Supplier invoice")

    def test_document_requires_organization(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Document.objects.create(
                    title="Supplier invoice",
                    original_filename="invoice.pdf",
                    source=Document.Source.MANUAL_UPLOAD,
                )

    def test_default_status_is_new(self):
        organization = create_organization()

        document = Document.objects.create(
            organization=organization,
            title="Bank statement",
            original_filename="statement.xml",
            source=Document.Source.BANK_IMPORT,
        )

        self.assertEqual(document.status, Document.Status.NEW)
        self.assertFalse(document.is_final)

    def test_mark_status_changes_status(self):
        organization = create_organization()

        document = Document.objects.create(
            organization=organization,
            title="Reviewed document",
            original_filename="reviewed.pdf",
            source=Document.Source.MAIL,
        )

        document.mark_status(Document.Status.APPROVED)
        document.refresh_from_db()

        self.assertEqual(document.status, Document.Status.APPROVED)
        self.assertTrue(document.is_final)

    def test_can_add_document_version(self):
        organization = create_organization()

        document = Document.objects.create(
            organization=organization,
            title="Versioned document",
            original_filename="invoice.pdf",
            source=Document.Source.MANUAL_UPLOAD,
        )

        version = DocumentVersion.objects.create(
            document=document,
            version_number=1,
            sha256="b" * 64,
            mime_type="application/pdf",
            size_bytes=23456,
            note="Original upload",
        )

        self.assertEqual(document.versions.count(), 1)
        self.assertEqual(str(version), "Versioned document v1")

    def test_can_add_document_tag(self):
        organization = create_organization()

        document = Document.objects.create(
            organization=organization,
            title="Tagged document",
            original_filename="invoice.pdf",
            source=Document.Source.MERIT_IMPORT,
        )

        tag = DocumentTag.objects.create(document=document, name="invoice")

        self.assertEqual(document.tags.count(), 1)
        self.assertEqual(str(tag), "invoice")
