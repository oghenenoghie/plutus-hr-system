import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.domain.employee_lifecycle import LifecycleStage
from app.domain.payroll.frequency import PayFrequency
from app.models.employee import EmploymentType, LifecycleState
from app.models.employee_history_event import EmployeeHistoryEventType


class EmployeeCreate(BaseModel):
    employee_number: str
    full_name: str
    state_of_residence: str
    state_of_origin: str | None = None
    employment_type: EmploymentType
    date_of_joining: date
    contract_end_date: date | None = None
    basic_minor: int
    housing_minor: int
    transport_minor: int
    other_earnings_minor: int = 0
    annual_rent_paid_minor: int = 0
    # Above the statutory minimum only; null means the rule set's rate.
    pension_employee_rate_ppm: int | None = Field(default=None, gt=0, le=1_000_000)
    pension_employer_rate_ppm: int | None = Field(default=None, gt=0, le=1_000_000)
    # Only some countries' statutory rules need these (app.compliance.engine).
    tax_half_shares: int | None = Field(default=None, ge=0)
    is_expatriate: bool | None = None
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
    branch_id: uuid.UUID | None = None
    job_grade_id: uuid.UUID | None = None
    shift_id: uuid.UUID | None = None


class EmployeeUpdate(BaseModel):
    """Partial update of anything recorded when the employee was created, so
    a record started with the minimum can be completed later. Lifecycle
    state is deliberately not settable here: termination goes through
    /final-settlements so the exit payslip and loan recovery always happen
    together, never a bare status flip. A field that can't be empty (see
    REQUIRED_EMPLOYEE_FIELDS) can be changed but not cleared."""

    employee_number: str | None = Field(default=None, min_length=1, max_length=64)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    employment_type: EmploymentType | None = None
    date_of_joining: date | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    nationality: str | None = None
    marital_status: str | None = None
    email: str | None = None
    phone: str | None = None
    residential_address: str | None = None
    next_of_kin_name: str | None = None
    next_of_kin_phone: str | None = None
    state_of_residence: str | None = None
    state_of_origin: str | None = None
    job_title: str | None = None
    contract_end_date: date | None = None
    manager_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    job_grade_id: uuid.UUID | None = None
    shift_id: uuid.UUID | None = None
    tin: str | None = None
    pfa_name: str | None = None
    rsa_pin: str | None = None
    nhf_number: str | None = None
    basic_minor: int | None = Field(default=None, ge=0)
    housing_minor: int | None = Field(default=None, ge=0)
    transport_minor: int | None = Field(default=None, ge=0)
    other_earnings_minor: int | None = Field(default=None, ge=0)
    annual_rent_paid_minor: int | None = Field(default=None, ge=0)
    pension_employee_rate_ppm: int | None = Field(default=None, gt=0, le=1_000_000)
    pension_employer_rate_ppm: int | None = Field(default=None, gt=0, le=1_000_000)
    tax_half_shares: int | None = Field(default=None, ge=0)
    is_expatriate: bool | None = None
    pay_frequency: PayFrequency | None = None
    annual_leave_entitlement_days: int | None = Field(default=None, ge=0)
    salary_masked: bool | None = None


PERSONAL_DETAIL_FIELDS = (
    "pfa_name",
    "rsa_pin",
    "nhf_number",
    "date_of_birth",
    "gender",
    "nationality",
    "marital_status",
    "email",
    "phone",
    "residential_address",
    "next_of_kin_name",
    "next_of_kin_phone",
)

# Columns an employee can't be without: PATCH may change them, never null them.
REQUIRED_EMPLOYEE_FIELDS = frozenset(
    {
        "employee_number",
        "full_name",
        "employment_type",
        "date_of_joining",
        "state_of_residence",
        "basic_minor",
        "housing_minor",
        "transport_minor",
        "other_earnings_minor",
        "annual_rent_paid_minor",
        "pay_frequency",
        "annual_leave_entitlement_days",
        "salary_masked",
    }
)


class LinkAccountRequest(BaseModel):
    account_id: uuid.UUID


class CreateEmployeeLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class CreateEmployeeLoginOut(BaseModel):
    account_id: uuid.UUID
    email: str
    login_code: str | None
    role: str


class EmployeeBulkImportRequest(BaseModel):
    """csv_content is the raw CSV text, header row included, with column
    names matching EmployeeCreate's own field names (see
    app.services.employee_import) — the app never hosts uploaded file
    bytes, so the caller reads the file client-side and posts its text."""

    csv_content: str


class EmployeeBulkImportRowError(BaseModel):
    row: int
    employee_number: str | None
    error: str


class EmployeeHistoryEventOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    event_type: EmployeeHistoryEventType
    effective_date: date
    detail: dict[str, Any]
    recorded_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EmployeeOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    account_id: uuid.UUID | None
    employee_number: str
    login_code: str | None
    full_name: str
    state_of_residence: str
    state_of_origin: str | None
    employment_type: EmploymentType
    lifecycle_state: LifecycleState
    lifecycle_stage: LifecycleStage
    date_of_joining: date
    contract_end_date: date | None
    job_title: str | None
    # Never sourced by from_attributes (Employee has no such column) — set
    # explicitly by _serialize() as a freshly minted signed URL, since a
    # stored one would just expire. Both null exactly when no photo has
    # ever been uploaded (photo_version == 0).
    photo_url: str | None = None
    photo_thumbnail_url: str | None = None
    manager_id: uuid.UUID | None
    department_id: uuid.UUID | None
    branch_id: uuid.UUID | None
    job_grade_id: uuid.UUID | None
    shift_id: uuid.UUID | None
    tin: str | None
    # Personal, contact and pension-scheme details: null unless the caller
    # manages employee records or is this employee (PERSONAL_DETAIL_FIELDS,
    # app.api.v1.employees._serialize), so a line manager never reads them.
    pfa_name: str | None = None
    rsa_pin: str | None = None
    nhf_number: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    nationality: str | None = None
    marital_status: str | None = None
    email: str | None = None
    phone: str | None = None
    residential_address: str | None = None
    next_of_kin_name: str | None = None
    next_of_kin_phone: str | None = None
    # Nullable, not always int: a MANAGER viewing a direct report gets these
    # masked to null (see app.domain.salary_masking) — an employee's exact
    # pay is not something their line manager can read off this endpoint,
    # only ADMIN/PAYROLL_MANAGER or the employee's own /me. Never actually
    # null for the employee's own record or for ADMIN/PAYROLL_MANAGER.
    basic_minor: int | None
    housing_minor: int | None
    transport_minor: int | None
    other_earnings_minor: int | None
    annual_rent_paid_minor: int | None
    pension_employee_rate_ppm: int | None = None
    pension_employer_rate_ppm: int | None = None
    tax_half_shares: int | None = None
    is_expatriate: bool | None = None
    pay_frequency: PayFrequency
    annual_leave_entitlement_days: int
    salary_masked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EmployeeBulkImportResult(BaseModel):
    created: list[EmployeeOut]
    row_errors: list[EmployeeBulkImportRowError]
