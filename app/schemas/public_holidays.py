import uuid
from datetime import date, datetime

from pydantic import BaseModel


class PublicHolidayCreate(BaseModel):
    holiday_date: date
    name: str


class PublicHolidayOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    holiday_date: date
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}
