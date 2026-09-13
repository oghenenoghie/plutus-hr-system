import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.employee_checklist_item import ChecklistItemStatus, ChecklistType


class ChecklistItemCreate(BaseModel):
    checklist_type: ChecklistType
    title: str
    due_date: date | None = None


class ChecklistItemOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    checklist_type: ChecklistType
    title: str
    status: ChecklistItemStatus
    due_date: date | None
    completed_at: datetime | None
    completed_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
