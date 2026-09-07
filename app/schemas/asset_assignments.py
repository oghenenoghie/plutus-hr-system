import uuid
from datetime import date, datetime

from pydantic import BaseModel


class AssetAssignmentCreate(BaseModel):
    employee_id: uuid.UUID
    assigned_date: date


class AssetAssignmentReturn(BaseModel):
    returned_date: date
    condition_notes: str | None = None


class AssetAssignmentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    asset_id: uuid.UUID
    employee_id: uuid.UUID
    assigned_date: date
    returned_date: date | None
    condition_notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
