import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.job_posting import JobPostingStatus


class JobPostingCreate(BaseModel):
    title: str
    department_id: uuid.UUID | None = None
    description: str | None = None
    opened_date: date


class JobPostingUpdate(BaseModel):
    title: str | None = None
    department_id: uuid.UUID | None = None
    description: str | None = None
    status: JobPostingStatus | None = None
    closed_date: date | None = None


class JobPostingOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    department_id: uuid.UUID | None
    title: str
    description: str | None
    status: JobPostingStatus
    opened_date: date
    closed_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}
