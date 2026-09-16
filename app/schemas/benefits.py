import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.benefit import BenefitFrequency


class BenefitPlanCreate(BaseModel):
    name: str
    frequency: BenefitFrequency
    description: str | None = None
    default_employee_cost_minor: int | None = None
    employer_cost_minor: int | None = None


class BenefitPlanOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    frequency: BenefitFrequency
    default_employee_cost_minor: int | None
    employer_cost_minor: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BenefitCreate(BaseModel):
    effective_date: date
    plan_id: uuid.UUID | None = None
    # Required when plan_id is omitted (an ad hoc benefit); optional
    # overrides of the plan's own values otherwise.
    name: str | None = None
    frequency: BenefitFrequency | None = None
    description: str | None = None
    value_minor: int | None = None
    employer_cost_minor: int | None = None
    end_date: date | None = None


class BenefitEnd(BaseModel):
    end_date: date


class BenefitOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    plan_id: uuid.UUID | None
    name: str
    description: str | None
    value_minor: int | None
    employer_cost_minor: int | None
    frequency: BenefitFrequency
    effective_date: date
    end_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BenefitDependentCreate(BaseModel):
    full_name: str
    relationship: str
    date_of_birth: date | None = None


class BenefitDependentOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    full_name: str
    relationship: str
    date_of_birth: date | None
    created_at: datetime

    model_config = {"from_attributes": True}
