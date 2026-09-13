import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.leave_encashment import LeaveEncashmentStatus


class LeaveEncashmentCreate(BaseModel):
    requested_date: date
    days: int
    amount_minor: int


class LeaveEncashmentOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    requested_date: date
    days: int
    amount_minor: int
    status: LeaveEncashmentStatus
    pay_run_id: uuid.UUID | None
    created_at: datetime
    decided_at: datetime | None

    model_config = {"from_attributes": True}
