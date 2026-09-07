import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.leave import LeaveStatus, LeaveType


class LeaveRequestCreate(BaseModel):
    leave_type: LeaveType
    start_date: date
    end_date: date
    days: int
    reason: str | None = None


class LeaveRequestOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type: LeaveType
    start_date: date
    end_date: date
    days: int
    status: LeaveStatus
    reason: str | None
    created_at: datetime
    decided_at: datetime | None

    model_config = {"from_attributes": True}


class LeaveBalanceOut(BaseModel):
    entitlement_days: int
    taken_days: int
    remaining_days: int
