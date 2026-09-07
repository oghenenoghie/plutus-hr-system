import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee, LifecycleState
from app.models.membership import Role
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.schemas.payroll import DisbursementOut, PayRunCreate, PayRunOut, PayslipOut
from app.services.disbursement import generate_disbursement_file
from app.services.payroll import run_pay_run

router = APIRouter(prefix="/pay-runs", tags=["pay-runs"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.post("", response_model=PayRunOut, status_code=status.HTTP_201_CREATED)
def create_and_run_pay_run(
    body: PayRunCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> PayRun:
    """Creates the pay run and processes it in the same call — there is no
    separate draft-then-run step in this API surface; run_pay_run's own
    transaction (the caller's tenant_session) already rolls back the whole
    thing on any employee's error, so a partially-processed run can't be
    left behind either way.
    """
    query = select(Employee).where(Employee.lifecycle_state == LifecycleState.ACTIVE)
    if body.employee_ids is not None:
        query = query.where(Employee.id.in_(body.employee_ids))
    employees = list(db.scalars(query))
    if not employees:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="no active employees to pay"
        )

    pay_run = PayRun(
        org_id=claims.org_id,
        period_start=body.period_start,
        period_end=body.period_end,
        frequency=body.frequency,
    )
    db.add(pay_run)
    db.flush()

    run_pay_run(db, org_id=claims.org_id, pay_run=pay_run, employees=employees)
    return pay_run


@router.get("", response_model=list[PayRunOut])
def list_pay_runs(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[PayRun]:
    return list(db.scalars(select(PayRun).order_by(PayRun.period_end.desc())))


@router.get("/me/payslips", response_model=list[PayslipOut])
def list_my_payslips(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[Payslip]:
    """Registered ahead of /{pay_run_id} so 'me' is never captured as a
    (invalid) pay_run_id path parameter."""
    return list(
        db.scalars(
            select(Payslip)
            .where(Payslip.employee_id == employee.id)
            .order_by(Payslip.period_end.desc())
        )
    )


@router.get("/{pay_run_id}", response_model=PayRunOut)
def get_pay_run(
    pay_run_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> PayRun:
    pay_run = db.get(PayRun, pay_run_id)
    if pay_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pay run not found")
    return pay_run


@router.get("/{pay_run_id}/payslips", response_model=list[PayslipOut])
def list_payslips_for_pay_run(
    pay_run_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[Payslip]:
    return list(db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)))


@router.get("/{pay_run_id}/disbursement", response_model=DisbursementOut)
def get_disbursement_file(
    pay_run_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> DisbursementOut:
    result = generate_disbursement_file(db, pay_run_id=pay_run_id)
    return DisbursementOut(
        csv_content=result.csv_content,
        total_minor=result.total_minor,
        skipped_employee_numbers=list(result.skipped_employee_numbers),
    )
