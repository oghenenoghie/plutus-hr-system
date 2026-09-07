import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.disciplinary_case import (
    DisciplinaryCaseAction,
    DisciplinaryCaseCategory,
    DisciplinaryCaseStatus,
)


class DisciplinaryCaseCreate(BaseModel):
    employee_id: uuid.UUID
    reported_by_id: uuid.UUID | None = None
    category: DisciplinaryCaseCategory
    description: str
    incident_date: date


class DisciplinaryCaseUpdate(BaseModel):
    category: DisciplinaryCaseCategory | None = None
    description: str | None = None
    status: DisciplinaryCaseStatus | None = None


class DisciplinaryCaseResolve(BaseModel):
    action_taken: DisciplinaryCaseAction
    resolution_notes: str | None = None


class DisciplinaryCaseOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    reported_by_id: uuid.UUID | None
    category: DisciplinaryCaseCategory
    description: str
    status: DisciplinaryCaseStatus
    incident_date: date
    action_taken: DisciplinaryCaseAction | None
    resolution_notes: str | None
    resolution_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}
