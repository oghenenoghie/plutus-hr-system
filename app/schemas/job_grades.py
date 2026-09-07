import uuid
from datetime import datetime

from pydantic import BaseModel


class JobGradeCreate(BaseModel):
    name: str
    level: int | None = None
    min_salary_minor: int | None = None
    max_salary_minor: int | None = None


class JobGradeUpdate(BaseModel):
    name: str | None = None
    level: int | None = None
    min_salary_minor: int | None = None
    max_salary_minor: int | None = None


class JobGradeOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    level: int | None
    min_salary_minor: int | None
    max_salary_minor: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
