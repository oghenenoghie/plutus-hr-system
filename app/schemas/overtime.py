import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.overtime import OvertimeStatus


class OvertimeCreate(BaseModel):
    work_date: date
    hours: Decimal
    rate_multiplier: Decimal
    amount_minor: int


class OvertimeOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    work_date: date
    hours: Decimal
    rate_multiplier: Decimal
    amount_minor: int
    status: OvertimeStatus
    pay_run_id: uuid.UUID | None
    created_at: datetime
    decided_at: datetime | None

    model_config = {"from_attributes": True}
