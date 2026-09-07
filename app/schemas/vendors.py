import uuid
from datetime import datetime

from pydantic import BaseModel


class VendorCreate(BaseModel):
    name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    tin: str | None = None
    contractor_id: uuid.UUID | None = None


class VendorUpdate(BaseModel):
    name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    tin: str | None = None


class VendorOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    contractor_id: uuid.UUID | None
    name: str
    contact_email: str | None
    contact_phone: str | None
    tin: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
