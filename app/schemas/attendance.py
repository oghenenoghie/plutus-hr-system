import uuid
from datetime import date, datetime

from pydantic import BaseModel


class AttendanceRecordOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    work_date: date
    clock_in_at: datetime | None
    clock_out_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
