import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.domain.payroll.payslip import PayslipComputation
from app.models.employee import Employee, LifecycleState
from app.models.membership import Role
from app.schemas.simulation import (
    LumpSumGrossUpOut,
    LumpSumGrossUpRequest,
    PackageGrossUpOut,
    PackageGrossUpRequest,
    PayRunSimulationOut,
    PayRunSimulationRequest,
    SimulationOut,
    SimulationRequest,
)
from app.services.simulation import (
    SimulationInput,
    simulate_pay_run,
    simulate_payslip,
    solve_lump_sum_gross_up,
    solve_package_gross_up,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _to_scenario(body: SimulationRequest) -> SimulationInput:
    return SimulationInput(**body.model_dump())


def _to_out(computation: PayslipComputation) -> SimulationOut:
    return SimulationOut(**asdict(computation))


@router.post("/payslip/{employee_id}", response_model=SimulationOut)
def simulate_employee_payslip(
    employee_id: uuid.UUID,
    body: SimulationRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> SimulationOut:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")

    computation = simulate_payslip(db, employee=employee, scenario=_to_scenario(body))
    return _to_out(computation)


@router.post("/pay-run", response_model=PayRunSimulationOut)
def simulate_org_pay_run(
    body: PayRunSimulationRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> PayRunSimulationOut:
    employees = list(
        db.scalars(select(Employee).where(Employee.lifecycle_state == LifecycleState.ACTIVE))
    )
    overrides = {
        employee_id: _to_scenario(scenario) for employee_id, scenario in body.overrides.items()
    }
    result = simulate_pay_run(
        db, employees=employees, period_end=body.period_end, overrides_by_employee_id=overrides
    )
    return PayRunSimulationOut(
        by_employee_id={eid: _to_out(c) for eid, c in result.by_employee_id.items()},
        total_gross_minor=result.total_gross_minor,
        total_employer_cost_minor=result.total_employer_cost_minor,
        total_net_minor=result.total_net_minor,
    )


@router.post("/gross-up/lump-sum/{employee_id}", response_model=LumpSumGrossUpOut)
def gross_up_lump_sum(
    employee_id: uuid.UUID,
    body: LumpSumGrossUpRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> LumpSumGrossUpOut:
    """For a one-off bonus/arrears/13th-month payment: the minimal gross
    that nets the employee at least target_net_minor from that payment
    alone. Nothing is persisted — apply the returned gross as
    other_earnings on the actual pay run yourself."""
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    gross_minor = solve_lump_sum_gross_up(
        db, employee=employee, period_end=body.period_end, target_net_minor=body.target_net_minor
    )
    return LumpSumGrossUpOut(gross_minor=gross_minor)


@router.post("/gross-up/package/{employee_id}", response_model=PackageGrossUpOut)
def gross_up_package(
    employee_id: uuid.UUID,
    body: PackageGrossUpRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> PackageGrossUpOut:
    """For 'pay this employee X net every period': the minimal
    basic/housing/transport package (scaled from the employee's current
    ratio) whose net pay is at least target_net_minor. Nothing is
    persisted — apply the returned components to the employee record
    yourself (PATCH /employees/{id})."""
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    result = solve_package_gross_up(
        db, employee=employee, period_end=body.period_end, target_net_minor=body.target_net_minor
    )
    return PackageGrossUpOut(
        basic_minor=result.basic_minor,
        housing_minor=result.housing_minor,
        transport_minor=result.transport_minor,
        computation=_to_out(result.computation),
    )
