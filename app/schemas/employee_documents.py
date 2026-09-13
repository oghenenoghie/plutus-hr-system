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
    storage_url: str
    expiry_date: date | None
    uploaded_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
