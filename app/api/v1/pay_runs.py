import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee, LifecycleState
from app.models.membership import Role
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payslip_delivery import PayslipDelivery
from app.schemas.payroll import (
    DisbursementOut,
    PayRunCreate,
    PayRunOut,
    PayRunReverseBody,
    PayslipDeliveryOut,
    PayslipOut,
)
from app.services.audit import record_audit_event
from app.services.disbursement import generate_disbursement_file
from app.services.payroll import reverse_pay_run, run_pay_run
from app.services.payslip_delivery import deliver_payslip_email
from app.services.payslip_pdf import render_payslip_pdf

router = APIRouter(prefix="/pay-runs", tags=["pay-runs"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.post("", response_model=PayRunOut, status_code=status.HTTP_201_CREATED)
def create_and_run_pay_run(
    body: PayRunCreate,
    background_tasks: BackgroundTasks,
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
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="pay_run.create",
        entity_type="pay_run",
        entity_id=pay_run.id,
        metadata={
            "employee_count": pay_run.employee_count,
            "gross_minor": pay_run.gross_minor,
            "period_start": body.period_start.isoformat(),
            "period_end": body.period_end.isoformat(),
        },
    )

    payslip_ids = list(db.scalars(select(Payslip.id).where(Payslip.pay_run_id == pay_run.id)))

    # Committed explicitly here, before scheduling background tasks, rather
    # than left to get_tenant_db's implicit commit-on-teardown: with
    # RequestIdMiddleware in the stack (Starlette's BaseHTTPMiddleware,
    # which runs the inner app in a separate task group), a scheduled
    # background task can start before a yield-dependency's teardown is
    # guaranteed to have committed — a background task opening its own
    # session could then fail to see the very payslips just created here.
    db.commit()

    for payslip_id in payslip_ids:
        background_tasks.add_task(
            deliver_payslip_email,
            org_id=claims.org_id,
            account_id=claims.account_id,
            role=claims.role,
            payslip_id=payslip_id,
        )
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


def _payslip_pdf_response(db: Session, payslip: Payslip) -> Response:
    employee = db.get(Employee, payslip.employee_id)
    organisation = db.get(Organisation, payslip.org_id)
    if employee is None or organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="payslip not found")
    pdf_bytes = render_payslip_pdf(organisation=organisation, employee=employee, payslip=payslip)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip-{payslip.period_end}.pdf"'},
    )


@router.get("/me/payslips/{payslip_id}/pdf")
def download_my_payslip_pdf(
    payslip_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> Response:
    payslip = db.get(Payslip, payslip_id)
    if payslip is None or payslip.employee_id != employee.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="payslip not found")
    return _payslip_pdf_response(db, payslip)


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


@router.post("/{pay_run_id}/reverse", response_model=PayRunOut)
def reverse_pay_run_endpoint(
    pay_run_id: uuid.UUID,
    body: PayRunReverseBody | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> PayRun:
    pay_run = db.get(PayRun, pay_run_id)
    if pay_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pay run not found")
    acknowledge_filed_or_remitted = body.acknowledge_filed_or_remitted if body else False
    try:
        reverse_pay_run(
            db,
            org_id=claims.org_id,
            pay_run=pay_run,
            acknowledge_filed_or_remitted=acknowledge_filed_or_remitted,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="pay_run.reverse",
        entity_type="pay_run",
        entity_id=pay_run.id,
        metadata={"acknowledge_filed_or_remitted": acknowledge_filed_or_remitted},
    )
    return pay_run


@router.get("/{pay_run_id}/payslips", response_model=list[PayslipOut])
def list_payslips_for_pay_run(
    pay_run_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[Payslip]:
    return list(db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)))


@router.get("/{pay_run_id}/payslips/{payslip_id}/pdf")
def download_payslip_pdf(
    pay_run_id: uuid.UUID,
    payslip_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    payslip = db.get(Payslip, payslip_id)
    if payslip is None or payslip.pay_run_id != pay_run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="payslip not found")
    return _payslip_pdf_response(db, payslip)


@router.get(
    "/{pay_run_id}/payslips/{payslip_id}/deliveries", response_model=list[PayslipDeliveryOut]
)
def list_payslip_deliveries(
    pay_run_id: uuid.UUID,
    payslip_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[PayslipDelivery]:
    payslip = db.get(Payslip, payslip_id)
    if payslip is None or payslip.pay_run_id != pay_run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="payslip not found")
    return list(
        db.scalars(
            select(PayslipDelivery)
            .where(PayslipDelivery.payslip_id == payslip_id)
            .order_by(PayslipDelivery.created_at.desc())
        )
    )


@router.post("/{pay_run_id}/payslips/{payslip_id}/resend", status_code=status.HTTP_202_ACCEPTED)
def resend_payslip_email(
    pay_run_id: uuid.UUID,
    payslip_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> None:
    payslip = db.get(Payslip, payslip_id)
    if payslip is None or payslip.pay_run_id != pay_run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="payslip not found")
    background_tasks.add_task(
        deliver_payslip_email,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        payslip_id=payslip_id,
    )
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="payslip.resend_email",
        entity_type="payslip",
        entity_id=payslip.id,
    )


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
