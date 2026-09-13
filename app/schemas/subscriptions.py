import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.subscription_plans import PlanCode
from app.models.subscription import SubscriptionStatus


class ChangePlanRequest(BaseModel):
    plan_code: PlanCode


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    plan_code: PlanCode
    status: SubscriptionStatus
    current_period_end: date
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageSummaryOut(BaseModel):
    plan_code: PlanCode
    plan_name: str
    employee_count: int
    employee_limit: int | None
    over_limit: bool
    monthly_price_minor: int
