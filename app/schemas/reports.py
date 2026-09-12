import uuid
from datetime import date

from pydantic import BaseModel


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
