import uuid
from datetime import date

from pydantic import BaseModel

from app.domain.payroll.frequency import PayFrequency


class SimulationRequest(BaseModel):
    period_end: date
    basic_minor: int | None = None
    housing_minor: int | None = None
    transport_minor: int | None = None
    other_earnings_minor: int | None = None
    annual_rent_paid_minor: int | None = None
    frequency: PayFrequency | None = None
    include_active_loan_deduction: bool = True


class SimulationOut(BaseModel):
    gross_minor: int
    pensionable_pay_minor: int
    pension_employee_minor: int
    pension_employer_minor: int
    nhf_minor: int
    cumulative_rent_relief_minor: int
    cumulative_chargeable_income_minor: int
    paye_minor: int
    loan_deduction_minor: int
    benefit_deduction_minor: int
    net_pay_minor: int


class PayRunSimulationRequest(BaseModel):
    period_end: date
    overrides: dict[uuid.UUID, SimulationRequest] = {}


class PayRunSimulationOut(BaseModel):
    by_employee_id: dict[uuid.UUID, SimulationOut]
    total_gross_minor: int
    total_employer_cost_minor: int
    total_net_minor: int


class LumpSumGrossUpRequest(BaseModel):
    period_end: date
    target_net_minor: int


class LumpSumGrossUpOut(BaseModel):
    gross_minor: int


class PackageGrossUpRequest(BaseModel):
    period_end: date
    target_net_minor: int


class PackageGrossUpOut(BaseModel):
    basic_minor: int
    housing_minor: int
    transport_minor: int
    computation: SimulationOut
