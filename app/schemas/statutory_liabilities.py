import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.statutory_liability import LiabilityScheme, LiabilityStatus


class StatutoryLiabilityOut(BaseModel):
    id: uuid.UUID
    pay_run_id: uuid.UUID | None
    scheme: LiabilityScheme
    state: str | None
    authority: str
    base_minor: int
    amount_minor: int
    period_start: date
    period_end: date
    due_date: date
    status: LiabilityStatus
    filed_at: datetime | None
    remitted_at: datetime | None
    remittance_reference: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RemitRequest(BaseModel):
    reference: str | None = None
