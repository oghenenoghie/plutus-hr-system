import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.candidate import CandidateStatus


class CandidateCreate(BaseModel):
    full_name: str
    email: str | None = None
    phone: str | None = None
    applied_date: date


class CandidateUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    status: CandidateStatus | None = None


class CandidateOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    job_posting_id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    status: CandidateStatus
    applied_date: date
    created_at: datetime

    model_config = {"from_attributes": True}
