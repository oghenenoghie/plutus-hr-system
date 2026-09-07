import uuid
from datetime import datetime

from pydantic import BaseModel


class ApiKeyCreate(BaseModel):
    name: str


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    key_prefix: str
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyOut):
    """Returned only from the create endpoint — the one time the
    plaintext key is ever available."""

    key: str
