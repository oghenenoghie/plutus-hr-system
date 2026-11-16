"""Files uploaded to an employee's record (a scanned ID, a signed contract,
a certificate), kept in the app's own object storage. The bytes are stored
privately and reached only through a signed link minted each time the
document is listed, never a stored or public URL (app/core/storage.py)."""

import re
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.storage import document_object_key, get_object_storage
from app.models.employee import Employee
from app.models.employee_document import DocumentCategory, EmployeeDocument

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

# What a document on an HR file usually is: a PDF, a scan or a photo taken on
# a phone, or a Word document.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "application/pdf": "PDF",
    "image/jpeg": "JPEG image",
    "image/png": "PNG image",
    "image/webp": "WebP image",
    "image/heic": "HEIC photo",
    "image/heif": "HEIF photo",
    "application/msword": "Word document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word document",
}

DOCUMENT_URL_TTL_SECONDS = 15 * 60


class InvalidDocumentError(ValueError):
    pass


def _safe_file_name(file_name: str | None) -> str:
    """The upload's own name, reduced to characters safe in a storage key."""
    name = (file_name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return name[-120:] or "document"


def upload_employee_document(
    db: Session,
    *,
    employee: Employee,
    uploaded_by: uuid.UUID | None,
    category: DocumentCategory,
    title: str,
    expiry_date: date | None,
    file_name: str | None,
    content_type: str | None,
    data: bytes,
) -> EmployeeDocument:
    title = title.strip()
    if not title:
        raise InvalidDocumentError("a document needs a title")
    if not data:
        raise InvalidDocumentError("the file is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise InvalidDocumentError(
            f"the file is {len(data) / (1024 * 1024):.1f} MB; documents can be up to "
            f"{MAX_DOCUMENT_BYTES // (1024 * 1024)} MB"
        )
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    if kind not in ALLOWED_CONTENT_TYPES:
        raise InvalidDocumentError(
            "documents can be PDFs, photos or scans (JPEG, PNG, WebP, HEIC) or Word documents"
        )

    safe_name = _safe_file_name(file_name)
    document = EmployeeDocument(
        id=uuid.uuid4(),
        org_id=employee.org_id,
        employee_id=employee.id,
        uploaded_by=uploaded_by,
        category=category,
        title=title,
        expiry_date=expiry_date,
        file_name=safe_name,
        content_type=kind,
        size_bytes=len(data),
    )
    document.storage_key = document_object_key(employee.org_id, employee.id, document.id, safe_name)
    get_object_storage().put_object(document.storage_key, data, content_type=kind)
    db.add(document)
    db.flush()
    return document


def document_url(document: EmployeeDocument, *, base_url: str) -> str | None:
    """Where the file can be opened: a fresh signed link to an uploaded file,
    or the link a document was recorded with."""
    if document.storage_key:
        return get_object_storage().presigned_url(
            document.storage_key, ttl_seconds=DOCUMENT_URL_TTL_SECONDS, base_url=base_url
        )
    return document.storage_url
