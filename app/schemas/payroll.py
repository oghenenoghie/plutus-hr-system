import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.domain.payroll.frequency import PayFrequency
from app.models.pay_run import PayRunStatus
from app.models.payslip_delivery import PayslipDeliveryStatus


class PayRunCreate(BaseModel):
    period_start: date
    period_end: date
    frequency: PayFrequency
    employee_ids: list[uuid.UUID] | None = None  # None = every active employee


class PayRunOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    period_start: date
    period_end: date
    frequency: PayFrequency
    status: PayRunStatus
    rule_version_id: str | None
    employee_count: int
    gross_minor: int
    net_minor: int
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class PayslipOut(BaseModel):
    id: uuid.UUID
    pay_run_id: uuid.UUID
    employee_id: uuid.UUID
    period_start: date
    period_end: date
    gross_minor: int
    pensionable_pay_minor: int
    pension_employee_minor: int
    pension_employer_minor: int
    nhf_minor: int
    paye_minor: int
    net_minor: int
    cumulative_chargeable_income_minor: int
    rule_version_id: str
    derivation: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class PayslipDeliveryOut(BaseModel):
    id: uuid.UUID
    payslip_id: uuid.UUID
    status: PayslipDeliveryStatus
    recipient_email: str
    provider_message_id: str | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DisbursementOut(BaseModel):
    csv_content: str
    total_minor: int
    skipped_employee_numbers: list[str]
