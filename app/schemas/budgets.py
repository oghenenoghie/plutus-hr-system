import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.chart_account import AccountType


class BudgetLineCreate(BaseModel):
    account_code: str
    amount_minor: int


class BudgetCreate(BaseModel):
    name: str
    department_id: uuid.UUID | None = None
    period_start: date
    period_end: date
    lines: list[BudgetLineCreate]


class BudgetLineOut(BaseModel):
    account_code: str
    account_name: str
    amount_minor: int


class BudgetOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    department_id: uuid.UUID | None
    name: str
    period_start: date
    period_end: date
    lines: list[BudgetLineOut]
    total_budgeted_minor: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BudgetLineActualOut(BaseModel):
    account_code: str
    account_name: str
    account_type: AccountType
    budgeted_minor: int
    actual_minor: int
    variance_minor: int


class BudgetVsActualOut(BaseModel):
    budget_id: uuid.UUID
    name: str
    period_start: date
    period_end: date
    lines: list[BudgetLineActualOut]
    total_budgeted_minor: int
    total_actual_minor: int
    total_variance_minor: int
