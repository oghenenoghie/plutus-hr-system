import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.training_enrollment import TrainingEnrollmentStatus


class TrainingEnrollmentCreate(BaseModel):
    employee_id: uuid.UUID
    enrolled_date: date


class TrainingEnrollmentUpdate(BaseModel):
    status: TrainingEnrollmentStatus | None = None
    completed_date: date | None = None
    score: int | None = None


class TrainingEnrollmentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    course_id: uuid.UUID
    employee_id: uuid.UUID
    status: TrainingEnrollmentStatus
    enrolled_date: date
    completed_date: date | None
    score: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
