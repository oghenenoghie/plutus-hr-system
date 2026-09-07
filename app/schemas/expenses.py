import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.expense import ExpenseStatus


class ExpenseCreate(BaseModel):
    category: str
    description: str
    amount_minor: int
    expense_date: date


class ExpenseOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    category: str
    description: str
    amount_minor: int
    expense_date: date
    status: ExpenseStatus
    created_at: datetime
    decided_at: datetime | None
    reimbursed_at: datetime | None

    model_config = {"from_attributes": True}
