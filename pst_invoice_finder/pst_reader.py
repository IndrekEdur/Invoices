from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import AttachmentInfo, EmailInfo, make_output_path
from .pdf_text import extract_pdf_preview


class MissingPstDependency(RuntimeError):
    pass


def _load_pypff() -> Any:
    try:
        import pypff  # type: ignore
    except ImportError as exc:
        raise MissingPstDependency(
            "PST lugemiseks on vaja pypff/libpff Python bindingut. "
            "Kui see on paigaldatud, töötab sama käsk otse .pst failiga."
        ) from exc
    return pypff


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "cp1257", "latin-1"):
            try:
                return value.decode(encoding, errors="ignore")
            except Exception:
                pass
        return value.decode(errors="ignore")
    return str(value)


def _first_attr(obj: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        try:
            value = getattr(obj, name)
            if callable(value):
                value = value()
            if value not in (None, ""):
                return value
        except Exception:
            continue
    return None


def _message_datetime(message: Any) -> datetime | None:
    value = _first_attr(
        message,
        (
            "client_submit_time",
            "delivery_time",
            "creation_time",
            "modification_time",
        ),
    )
    return value if isinstance(value, datetime) else None


def _message_body(message: Any) -> str:
    value = _first_attr(message, ("plain_text_body", "html_body", "rtf_body"))
    return _text(value).strip()


def _attachment_filename(attachment: Any, index: int) -> str:
    value = _first_attr(
        attachment,
        (
            "long_filename",
            "filename",
            "name",
            "display_name",
        ),
    )
    name = _text(value).strip()
    return name or f"attachment-{index + 1}.bin"


def _attachment_size(attachment: Any) -> int | None:
    value = _first_attr(attachment, ("size", "data_size"))
    return value if isinstance(value, int) else None


def _read_attachment_bytes(attachment: Any) -> bytes | None:
    for method_name in ("read_buffer", "read", "get_data"):
        method = getattr(attachment, method_name, None)
        if callable(method):
            try:
                data = method()
                if isinstance(data, bytes):
                    return data
            except Exception:
                continue
    return None


def _folder_name(folder: Any) -> str:
    return _text(_first_attr(folder, ("name", "display_name"))).strip() or "Root"


def _walk_folder(folder: Any, path_parts: list[str]) -> Iterator[tuple[list[str], Any]]:
    yield path_parts, folder

    count = int(_first_attr(folder, ("number_of_sub_folders",)) or 0)
    for index in range(count):
        try:
            sub_folder = folder.get_sub_folder(index)
        except Exception:
            continue
        yield from _walk_folder(sub_folder, [*path_parts, _folder_name(sub_folder)])


def iter_pst_emails(pst_path: Path, attachment_dir: Path | None = None, save_attachments: bool = True) -> Iterator[EmailInfo]:
    pypff = _load_pypff()
    pst = pypff.file()
    pst.open(str(pst_path))

    try:
        root = pst.get_root_folder()
        for folder_parts, folder in _walk_folder(root, [_folder_name(root)]):
            folder_path = "/".join(folder_parts)
            message_count = int(_first_attr(folder, ("number_of_messages",)) or 0)
            for message_index in range(message_count):
                try:
                    message = folder.get_message(message_index)
                    yield _email_from_message(message, folder_path, attachment_dir, save_attachments)
                except Exception:
                    continue
    finally:
        try:
            pst.close()
        except Exception:
            pass


def _email_from_message(
    message: Any,
    folder_path: str,
    attachment_dir: Path | None,
    save_attachments: bool,
) -> EmailInfo:
    sent_at = _message_datetime(message)
    body = _message_body(message)
    attachments: list[AttachmentInfo] = []

    attachment_count = int(_first_attr(message, ("number_of_attachments",)) or 0)
    for index in range(attachment_count):
        try:
            attachment = message.get_attachment(index)
        except Exception:
            continue

        filename = _attachment_filename(attachment, index)
        info = AttachmentInfo(filename=filename, size=_attachment_size(attachment))

        if save_attachments and attachment_dir:
            data = _read_attachment_bytes(attachment)
            if data:
                target = make_output_path(attachment_dir, sent_at, folder_path, filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                info.saved_path = str(target)
                if target.suffix.lower() == ".pdf":
                    info.text_preview = extract_pdf_preview(target)

        attachments.append(info)

    return EmailInfo(
        folder=folder_path,
        subject=_text(_first_attr(message, ("subject",))).strip(),
        sender_name=_text(_first_attr(message, ("sender_name",))).strip() or None,
        sender_email=_text(_first_attr(message, ("sender_email_address", "sender_email"))).strip() or None,
        sent_at=sent_at,
        body_preview=body[:3000],
        attachments=attachments,
    )
