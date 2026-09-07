import uuid
from datetime import datetime

from pydantic import BaseModel


class BranchCreate(BaseModel):
    name: str
    state: str | None = None
    address: str | None = None
    manager_id: uuid.UUID | None = None


class BranchUpdate(BaseModel):
    name: str | None = None
    state: str | None = None
    address: str | None = None
    manager_id: uuid.UUID | None = None


class BranchOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    state: str | None
    address: str | None
    manager_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
