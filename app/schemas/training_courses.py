import uuid
from datetime import datetime

from pydantic import BaseModel


class TrainingCourseCreate(BaseModel):
    title: str
    description: str | None = None
    provider: str | None = None
    duration_hours: int | None = None


class TrainingCourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    provider: str | None = None
    duration_hours: int | None = None


class TrainingCourseOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    title: str
    description: str | None
    provider: str | None
    duration_hours: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
