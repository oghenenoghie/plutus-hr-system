import uuid

from pydantic import BaseModel


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


class PayeByStateLineOut(BaseModel):
    state_of_residence: str
    employee_count: int
    total_paye_minor: int


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
