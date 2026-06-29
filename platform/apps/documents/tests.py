import hashlib
import shutil
import tempfile
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase

from apps.core.models import AuditEvent
from apps.core.services import CreateOrganizationCommand, OrganizationService
from apps.workflow.models import WorkflowDefinition, WorkflowEvent, WorkflowInstance, WorkflowState

from .models import Document, DocumentTag, DocumentVersion
from .services import DocumentStorageService, StoreDocumentCommand


def create_organization(name="Documents Org"):
    return OrganizationService.create(CreateOrganizationCommand(name=name))


def create_document_workflow():
    workflow = WorkflowDefinition.objects.create(code="document-processing", name="Document processing")
    WorkflowState.objects.create(workflow=workflow, code="received", name="Received", is_initial=True)
    return workflow


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


class DocumentStorageServiceTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

    def test_stores_document(self):
        organization = create_organization()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
                title="Uploaded invoice",
            )
        )

        self.assertIsNotNone(document.id)
        self.assertEqual(document.organization, organization)
        self.assertEqual(document.title, "Uploaded invoice")
        self.assertEqual(document.original_filename, "invoice.pdf")
        self.assertEqual(document.source, Document.Source.MANUAL_UPLOAD)
        self.assertTrue(document.file.name)

    def test_store_without_workflow_still_works(self):
        organization = create_organization()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
            )
        )

        self.assertIsNotNone(document.id)
        self.assertEqual(WorkflowInstance.objects.count(), 0)

    def test_creates_document_version_number_one(self):
        organization = create_organization()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
            )
        )

        version = document.versions.get()
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.sha256, document.sha256)
        self.assertEqual(version.size_bytes, document.size_bytes)
        self.assertEqual(version.mime_type, document.mime_type)
        self.assertTrue(version.file.name)

    def test_sha256_is_calculated(self):
        organization = create_organization()
        content = b"invoice content"
        uploaded_file = SimpleUploadedFile("invoice.pdf", content, content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
            )
        )

        self.assertEqual(document.sha256, hashlib.sha256(content).hexdigest())

    def test_size_bytes_is_calculated(self):
        organization = create_organization()
        content = b"123456789"
        uploaded_file = SimpleUploadedFile("invoice.pdf", content, content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
            )
        )

        self.assertEqual(document.size_bytes, len(content))

    def test_mime_type_is_set(self):
        organization = create_organization()
        uploaded_file = SimpleUploadedFile("statement.xml", b"<xml />", content_type="application/octet-stream")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="statement.xml",
            )
        )

        self.assertIn(document.mime_type, {"application/xml", "text/xml"})

    def test_metadata_defaults_to_empty_dict(self):
        organization = create_organization()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
            )
        )

        self.assertEqual(document.metadata, {})

    def test_caller_metadata_is_not_mutated(self):
        organization = create_organization()
        metadata = {"supplier": "Example"}
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
                metadata=metadata,
            )
        )

        document.metadata["supplier"] = "Changed"
        self.assertEqual(metadata, {"supplier": "Example"})

    def test_audit_event_is_created(self):
        organization = create_organization()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
            )
        )

        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="document.stored",
                organization=organization,
                object_type="Document",
                object_id=str(document.uuid),
            ).exists()
        )

    def test_transaction_rolls_back_when_audit_fails(self):
        organization = create_organization()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        with patch("apps.documents.services.storage.AuditService.record", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                DocumentStorageService.store(
                    StoreDocumentCommand(
                        organization=organization,
                        file=uploaded_file,
                        original_filename="invoice.pdf",
                    )
                )

        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentVersion.objects.count(), 0)

    def test_store_with_workflow_creates_workflow_instance(self):
        organization = create_organization()
        workflow = create_document_workflow()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
                workflow=workflow,
            )
        )

        instance = WorkflowInstance.objects.get(entity_uuid=document.uuid)
        self.assertEqual(instance.workflow, workflow)

    def test_workflow_instance_links_to_document_identity(self):
        organization = create_organization()
        workflow = create_document_workflow()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
                workflow=workflow,
            )
        )

        instance = WorkflowInstance.objects.get()
        self.assertEqual(instance.entity_type, "document")
        self.assertEqual(instance.entity_uuid, document.uuid)

    def test_workflow_start_creates_workflow_events(self):
        organization = create_organization()
        workflow = create_document_workflow()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        document = DocumentStorageService.store(
            StoreDocumentCommand(
                organization=organization,
                file=uploaded_file,
                original_filename="invoice.pdf",
                workflow=workflow,
            )
        )

        instance = WorkflowInstance.objects.get(entity_uuid=document.uuid)
        self.assertEqual(
            list(instance.events.values_list("event_type", flat=True)),
            [WorkflowEvent.Type.WORKFLOW_STARTED, WorkflowEvent.Type.STATE_ENTERED],
        )

    def test_transaction_rolls_back_when_workflow_start_fails(self):
        organization = create_organization()
        workflow = create_document_workflow()
        uploaded_file = SimpleUploadedFile("invoice.pdf", b"invoice content", content_type="application/pdf")

        with patch("apps.documents.services.storage.WorkflowEngine.start", side_effect=RuntimeError("workflow failed")):
            with self.assertRaises(RuntimeError):
                DocumentStorageService.store(
                    StoreDocumentCommand(
                        organization=organization,
                        file=uploaded_file,
                        original_filename="invoice.pdf",
                        workflow=workflow,
                    )
                )

        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentVersion.objects.count(), 0)
        self.assertEqual(WorkflowInstance.objects.count(), 0)
