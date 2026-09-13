import uuid
from datetime import date, datetime

from pydantic import BaseModel


class ShiftRosterEntryCreate(BaseModel):
    employee_id: uuid.UUID
    shift_id: uuid.UUID
    start_date: date
    end_date: date


class ShiftRosterEntryOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    shift_id: uuid.UUID
    work_date: date
    created_at: datetime

    model_config = {"from_attributes": True}
