import uuid
from datetime import date, datetime

from pydantic import BaseModel


class FinalSettlementCreate(BaseModel):
    termination_date: date
    gratuity_minor: int
    leave_days_paid_out: int
    leave_payout_minor: int


class FinalSettlementOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    payslip_id: uuid.UUID
    termination_date: date
    leave_days_paid_out: int
    leave_payout_minor: int
    gratuity_minor: int
    outstanding_loan_recovered_minor: int
    net_settlement_minor: int
    created_at: datetime

    model_config = {"from_attributes": True}
