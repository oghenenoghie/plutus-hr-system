import uuid
from datetime import date

from pydantic import BaseModel

from app.domain.aging import AgingBucket
from app.models.bill import BillStatus


class PayrollCostLineOut(BaseModel):
    pay_run_id: uuid.UUID
    period_start: date
    period_end: date
    department_id: uuid.UUID | None
    department_name: str | None
    employee_count: int
    gross_minor: int
    employer_cost_minor: int
    net_minor: int


class AgingLineOut(BaseModel):
    entity_id: uuid.UUID
    counterparty_name: str
    reference_number: str
    due_date: date
    amount_minor: int
    bucket: AgingBucket


class VendorStatementLineOut(BaseModel):
    bill_id: uuid.UUID
    bill_number: str
    bill_date: date
    amount_minor: int
    status: BillStatus
    running_balance_minor: int
