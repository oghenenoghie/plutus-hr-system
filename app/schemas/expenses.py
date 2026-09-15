import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.expense import ExpensePaymentMethod, ExpenseStatus


class ExpenseCreate(BaseModel):
    category: str
    description: str
    amount_minor: int
    expense_date: date
    receipt_url: str | None = None
    payment_method: ExpensePaymentMethod = ExpensePaymentMethod.REIMBURSEMENT


class ExpenseOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    category: str
    description: str
    amount_minor: int
    expense_date: date
    receipt_url: str | None
    payment_method: ExpensePaymentMethod
    status: ExpenseStatus
    created_at: datetime
    decided_at: datetime | None
    reimbursed_at: datetime | None

    model_config = {"from_attributes": True}


class ExpensePolicyLimitUpsert(BaseModel):
    max_amount_minor: int


class ExpensePolicyLimitOut(BaseModel):
    id: uuid.UUID
    category: str
    max_amount_minor: int
    created_at: datetime

    model_config = {"from_attributes": True}
