from pydantic import BaseModel

from app.compliance.multicountry import TaxStatus


class PayeEstimateRequest(BaseModel):
    annual_gross_minor: int
    annual_rent_minor: int = 0


class PayeEstimateOut(BaseModel):
    rule_version_id: str
    # The assumed 50/30/20 basic/housing/transport split this estimate is
    # built on — never what a real payslip uses (that reads each
    # employee's actual stored components; see process_employee_payslip).
    basic_minor: int
    housing_minor: int
    transport_minor: int
    gross_annual_minor: int
    pension_employee_annual_minor: int
    nhf_annual_minor: int
    rent_relief_annual_minor: int
    chargeable_income_annual_minor: int
    paye_annual_minor: int
    paye_monthly_minor: int
    net_annual_minor: int
    net_monthly_minor: int


class CountryProfileOut(BaseModel):
    code: str
    name: str
    currency: str
    tax_authority: str
    status: TaxStatus
    enabled_modules: list[str]
    # Whether an organisation can run on this country now: its rules are
    # approved and encoded as a rule version.
    selectable: bool
