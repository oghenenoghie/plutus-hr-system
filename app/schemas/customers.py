import uuid
from datetime import datetime

from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    tin: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    tin: str | None = None


class CustomerOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    contact_email: str | None
    contact_phone: str | None
    tin: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
