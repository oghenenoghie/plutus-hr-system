import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.document_template import DocumentType
from app.models.generated_document import GeneratedDocumentStatus


class DocumentTemplateCreate(BaseModel):
    document_type: DocumentType
    name: str
    body_template: str


class DocumentTemplateOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    document_type: DocumentType
    name: str
    body_template: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GenerateDocumentRequest(BaseModel):
    template_id: uuid.UUID
    extra_context: dict[str, str] = {}


class SignDocumentRequest(BaseModel):
    signed_by_name: str


class GeneratedDocumentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    template_id: uuid.UUID
    employee_id: uuid.UUID
    document_type: DocumentType
    rendered_content: str
    status: GeneratedDocumentStatus
    sent_at: datetime | None
    signed_at: datetime | None
    signed_by_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
