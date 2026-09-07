import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.performance_review import PerformanceReviewStatus


class PerformanceReviewCreate(BaseModel):
    employee_id: uuid.UUID
    reviewer_id: uuid.UUID | None = None
    period_start: date
    period_end: date
    goals: str | None = None


class PerformanceReviewSubmit(BaseModel):
    rating: int | None = None
    manager_comments: str | None = None


class PerformanceReviewAcknowledge(BaseModel):
    employee_comments: str | None = None


class PerformanceReviewOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    reviewer_id: uuid.UUID | None
    period_start: date
    period_end: date
    status: PerformanceReviewStatus
    rating: int | None
    goals: str | None
    manager_comments: str | None
    employee_comments: str | None
    submitted_date: date | None
    acknowledged_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}
