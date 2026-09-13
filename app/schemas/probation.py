import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.probation_period import ProbationStatus


class ProbationPeriodCreate(BaseModel):
    start_date: date
    end_date: date


class ProbationExtendRequest(BaseModel):
    new_end_date: date
    notes: str | None = None


class ProbationDecisionRequest(BaseModel):
    outcome: ProbationStatus
    notes: str | None = None


class ProbationPeriodOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    start_date: date
    end_date: date
    status: ProbationStatus
    decided_date: date | None
    decided_by: uuid.UUID | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
