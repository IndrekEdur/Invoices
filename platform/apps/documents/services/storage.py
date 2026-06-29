import hashlib
import mimetypes

from django.core.files.base import ContentFile
from django.db import transaction

from apps.core.services import AuditService

from ..models import Document, DocumentVersion


class DocumentStorageService:
    """Central workflow for storing files as Document root aggregates."""

    @staticmethod
    def store(command):
        content = DocumentStorageService._read_file_content(command.file)
        sha256 = hashlib.sha256(content).hexdigest()
        size_bytes = len(content)
        mime_type = DocumentStorageService._detect_mime_type(command.original_filename, command.file)
        metadata = dict(command.metadata or {})
        title = command.title or command.original_filename

        with transaction.atomic():
            document = Document.objects.create(
                organization=command.organization,
                title=title,
                original_filename=command.original_filename,
                source=command.source,
                file=ContentFile(content, name=command.original_filename),
                sha256=sha256,
                mime_type=mime_type,
                size_bytes=size_bytes,
                metadata=metadata,
            )
            DocumentVersion.objects.create(
                document=document,
                version_number=1,
                file=ContentFile(content, name=command.original_filename),
                sha256=sha256,
                mime_type=mime_type,
                size_bytes=size_bytes,
                note="Initial stored version",
            )
            AuditService.record(
                event_type="document.stored",
                message=f"Document stored: {document.original_filename}",
                organization=command.organization,
                actor=command.actor,
                object_type="Document",
                object_id=str(document.uuid),
                metadata={
                    "source": document.source,
                    "sha256": document.sha256,
                    "size_bytes": document.size_bytes,
                    "mime_type": document.mime_type,
                },
            )

            return document

    @staticmethod
    def _read_file_content(file):
        if hasattr(file, "seek"):
            file.seek(0)

        if hasattr(file, "chunks"):
            content = b"".join(file.chunks())
        else:
            content = file.read()

        if hasattr(file, "seek"):
            file.seek(0)

        return content

    @staticmethod
    def _detect_mime_type(filename, file):
        detected_mime_type, _encoding = mimetypes.guess_type(filename)
        if detected_mime_type:
            return detected_mime_type

        return getattr(file, "content_type", "") or ""
