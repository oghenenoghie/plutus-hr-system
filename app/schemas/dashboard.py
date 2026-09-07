from pydantic import BaseModel

from app.schemas.payroll import PayRunOut


class OrgSummaryOut(BaseModel):
    active_employee_count: int
    last_completed_pay_run: PayRunOut | None
    outstanding_liability_minor: int
    pending_leave_request_count: int
    pending_expense_count: int
