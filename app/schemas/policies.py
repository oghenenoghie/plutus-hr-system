import uuid
from datetime import date, datetime

from pydantic import BaseModel


class PolicyCreate(BaseModel):
    title: str
    body: str
    category: str | None = None
    effective_date: date | None = None


class PolicyUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    category: str | None = None
    effective_date: date | None = None


class PolicyOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    title: str
    category: str | None
    body: str
    effective_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}
