import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.benefit import BenefitFrequency


class BenefitCreate(BaseModel):
    name: str
    frequency: BenefitFrequency
    effective_date: date
    description: str | None = None
    value_minor: int | None = None
    end_date: date | None = None


class BenefitEnd(BaseModel):
    end_date: date


class BenefitOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    name: str
    description: str | None
    value_minor: int | None
    frequency: BenefitFrequency
    effective_date: date
    end_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}
