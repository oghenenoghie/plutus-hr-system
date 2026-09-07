import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.loan import LoanStatus


class LoanCreate(BaseModel):
    principal_minor: int
    num_installments: int
    start_date: date


class LoanOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    principal_minor: int
    num_installments: int
    installment_minor: int
    start_date: date
    status: LoanStatus
    outstanding_minor: int
    created_at: datetime

    model_config = {"from_attributes": True}
