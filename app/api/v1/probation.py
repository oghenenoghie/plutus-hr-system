import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.membership import Role
from app.models.probation_period import ProbationPeriod
from app.schemas.probation import (
    ProbationDecisionRequest,
    ProbationExtendRequest,
    ProbationPeriodCreate,
    ProbationPeriodOut,
)
from app.services.probation import decide_probation, extend_probation, register_probation_period

router = APIRouter(tags=["probation"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_employee_or_404(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    return employee


def _get_period_or_404(db: Session, period_id: uuid.UUID) -> ProbationPeriod:
    period = db.get(ProbationPeriod, period_id)
    if period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="probation period not found"
        )
    return period


@router.post(
    "/employees/{employee_id}/probation-periods",
    response_model=ProbationPeriodOut,
    status_code=status.HTTP_201_CREATED,
)
def create_probation_period(
    employee_id: uuid.UUID,
    body: ProbationPeriodCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> ProbationPeriod:
    _get_employee_or_404(db, employee_id)
    try:
        return register_probation_period(
            db, org_id=claims.org_id, employee_id=employee_id, **body.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/employees/{employee_id}/probation-periods", response_model=list[ProbationPeriodOut])
def list_probation_periods(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[ProbationPeriod]:
    _get_employee_or_404(db, employee_id)
    return list(
        db.scalars(
            select(ProbationPeriod)
            .where(ProbationPeriod.employee_id == employee_id)
            .order_by(ProbationPeriod.created_at)
        )
    )


@router.post("/probation-periods/{period_id}/extend", response_model=ProbationPeriodOut)
def extend(
    period_id: uuid.UUID,
    body: ProbationExtendRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> ProbationPeriod:
    period = _get_period_or_404(db, period_id)
    try:
        extend_probation(db, period, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return period


@router.post("/probation-periods/{period_id}/decide", response_model=ProbationPeriodOut)
def decide(
    period_id: uuid.UUID,
    body: ProbationDecisionRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> ProbationPeriod:
    period = _get_period_or_404(db, period_id)
    try:
        decide_probation(
            db,
            period,
            outcome=body.outcome,
            decided_by=claims.account_id,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return period
