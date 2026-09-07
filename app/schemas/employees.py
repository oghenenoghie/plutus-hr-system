import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.payroll.frequency import PayFrequency
from app.models.employee import EmploymentType, LifecycleState


class EmployeeCreate(BaseModel):
    employee_number: str
    full_name: str
    state_of_residence: str
    employment_type: EmploymentType
    date_of_joining: date
    basic_minor: int
    housing_minor: int
    transport_minor: int
    other_earnings_minor: int = 0
    annual_rent_paid_minor: int = 0
    pay_frequency: PayFrequency = PayFrequency.MONTHLY
    annual_leave_entitlement_days: int = 20

    date_of_birth: date | None = None
    gender: str | None = None
    nationality: str | None = None
    marital_status: str | None = None
    email: str | None = None
    phone: str | None = None
    residential_address: str | None = None
    next_of_kin_name: str | None = None
    next_of_kin_phone: str | None = None
    tin: str | None = None
    pfa_name: str | None = None
    rsa_pin: str | None = None
    nhf_number: str | None = None
    job_title: str | None = None
    manager_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    job_grade_id: uuid.UUID | None = None


class EmployeeUpdate(BaseModel):
    """Partial update — only pay components, routing fields, and manager/
    job metadata. Lifecycle state is deliberately not settable here:
    termination goes through /final-settlements so the exit payslip and
    loan recovery always happen together, never a bare status flip."""

    full_name: str | None = None
    state_of_residence: str | None = None
    job_title: str | None = None
    manager_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    job_grade_id: uuid.UUID | None = None
    tin: str | None = None
    pfa_name: str | None = None
    rsa_pin: str | None = None
    nhf_number: str | None = None
    basic_minor: int | None = None
    housing_minor: int | None = None
    transport_minor: int | None = None
    other_earnings_minor: int | None = None
    annual_rent_paid_minor: int | None = None
    pay_frequency: PayFrequency | None = None
    annual_leave_entitlement_days: int | None = None


class LinkAccountRequest(BaseModel):
    account_id: uuid.UUID


class EmployeeOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    account_id: uuid.UUID | None
    employee_number: str
    full_name: str
    state_of_residence: str
    employment_type: EmploymentType
    lifecycle_state: LifecycleState
    date_of_joining: date
    job_title: str | None
    manager_id: uuid.UUID | None
    department_id: uuid.UUID | None
    job_grade_id: uuid.UUID | None
    tin: str | None
    basic_minor: int
    housing_minor: int
    transport_minor: int
    other_earnings_minor: int
    annual_rent_paid_minor: int
    pay_frequency: PayFrequency
    annual_leave_entitlement_days: int
    created_at: datetime

    model_config = {"from_attributes": True}
