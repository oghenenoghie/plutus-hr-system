import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.employee_document import DocumentCategory


class EmployeeDocumentCreate(BaseModel):
    category: DocumentCategory
    title: str
    storage_url: str
    expiry_date: date | None = None


class EmployeeDocumentUpdate(BaseModel):
    category: DocumentCategory | None = None
    title: str | None = None
    expiry_date: date | None = None


class EmployeeDocumentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    category: DocumentCategory
    title: str
    # Where to open the file: for an uploaded file, a signed link that
    # expires after a few minutes (list the documents again for a new one);
    # otherwise the link the document was recorded with.
    storage_url: str | None
    # Set for a file uploaded to the app; None for a recorded link.
    file_name: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    expiry_date: date | None
    uploaded_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
