import uuid

from pydantic import BaseModel


class StatutoryAmountOut(BaseModel):
    code: str
    name: str
    kind: str  # employee_contribution, employer_contribution or income_tax
    amount_minor: int

    model_config = {"from_attributes": True}


class PayrollRegisterLineOut(BaseModel):
    employee_id: uuid.UUID
    employee_number: str
    full_name: str
    gross_minor: int
    pension_employee_minor: int
    pension_employer_minor: int
    nhf_minor: int
    paye_minor: int
    loan_deduction_minor: int
    benefit_deduction_minor: int
    union_dues_deduction_minor: int
    net_minor: int
    # An engine country's statutory lines; empty for Nigeria, whose figures
    # are the pension, NHF and PAYE fields above.
    statutory_lines: list[StatutoryAmountOut] = []


class PayeByStateLineOut(BaseModel):
    state_of_residence: str
    employee_count: int
    total_paye_minor: int


class StatutorySummaryLineOut(BaseModel):
    code: str
    name: str
    kind: str
    authority: str
    employee_count: int
    base_minor: int
    amount_minor: int


class AnnualTaxReconciliationOut(BaseModel):
    employee_id: uuid.UUID
    employee_number: str
    full_name: str
    tin: str | None
    tax_year: int
    total_gross_minor: int
    total_pension_employee_minor: int
    total_nhf_minor: int
    total_paye_minor: int
    payslip_count: int
    # An engine country's lines totalled for the year; empty for Nigeria.
    statutory_totals: list[StatutoryAmountOut] = []
