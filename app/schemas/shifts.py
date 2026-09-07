import uuid
from datetime import datetime, time

from pydantic import BaseModel


class ShiftCreate(BaseModel):
    name: str
    start_time: time
    end_time: time


class ShiftUpdate(BaseModel):
    name: str | None = None
    start_time: time | None = None
    end_time: time | None = None


class ShiftOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    start_time: time
    end_time: time
    created_at: datetime

    model_config = {"from_attributes": True}
