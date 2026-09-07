import uuid
from datetime import datetime

from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    name: str
    manager_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    manager_id: uuid.UUID | None = None


class DepartmentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    manager_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
