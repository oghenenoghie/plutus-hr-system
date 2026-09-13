import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.domain.payroll.frequency import PayFrequency
from app.models.pay_run import PayRunStatus
from app.models.pay_run_variance_flag import VarianceFlagType
from app.models.payslip_delivery import PayslipDeliveryStatus
from app.models.payslip_disbursement_record import DisbursementStatus


class PayRunCreate(BaseModel):
    period_start: date
    period_end: date
    frequency: PayFrequency
    employee_ids: list[uuid.UUID] | None = None  # None = every active employee


class PayRunValidateRequest(BaseModel):
    override_variance: bool = False


class PayRunOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    period_start: date
    period_end: date
    frequency: PayFrequency
    status: PayRunStatus
    employee_ids: list[uuid.UUID]
    rule_version_id: str | None
    employee_count: int
    gross_minor: int
    net_minor: int
    created_at: datetime
    validated_at: datetime | None
    locked_at: datetime | None
    locked_by: uuid.UUID | None
    disbursed_at: datetime | None
    disbursed_by: uuid.UUID | None
    reversed_at: datetime | None

    model_config = {"from_attributes": True}


class PayRunVarianceFlagOut(BaseModel):
    id: uuid.UUID
    pay_run_id: uuid.UUID
    employee_id: uuid.UUID
    flag_type: VarianceFlagType
    detail: dict[str, Any]
    acknowledged: bool
    acknowledged_at: datetime | None
    created_at: datetime

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


class DisbursementOutcomeCreate(BaseModel):
    status: DisbursementStatus
    reference: str | None = None
    note: str | None = None


class DisbursementOutcomeOut(BaseModel):
    id: uuid.UUID
    payslip_id: uuid.UUID
    status: DisbursementStatus
    reference: str | None
    note: str | None
    recorded_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
