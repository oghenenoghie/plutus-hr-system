import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.benefit import Benefit
from app.models.employee import Employee
from app.models.membership import Role
from app.schemas.benefits import BenefitCreate, BenefitEnd, BenefitOut
from app.services.audit import record_audit_event
from app.services.benefits import assign_benefit, end_benefit

router = APIRouter(prefix="/benefits", tags=["benefits"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.post(
    "/employees/{employee_id}", response_model=BenefitOut, status_code=status.HTTP_201_CREATED
)
def assign_employee_benefit(
    employee_id: uuid.UUID,
    body: BenefitCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Benefit:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")

    try:
        benefit = assign_benefit(
            db,
            org_id=claims.org_id,
            employee_id=employee_id,
            name=body.name,
            frequency=body.frequency,
            effective_date=body.effective_date,
            description=body.description,
            value_minor=body.value_minor,
            end_date=body.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="benefit.assign",
        entity_type="benefit",
        entity_id=benefit.id,
        metadata={"employee_id": str(employee_id), "name": benefit.name},
    )
    return benefit


@router.get("/employees/{employee_id}", response_model=list[BenefitOut])
def list_employee_benefits(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[Benefit]:
    return list(db.scalars(select(Benefit).where(Benefit.employee_id == employee_id)))


@router.get("/me", response_model=list[BenefitOut])
def list_my_benefits(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[Benefit]:
    return list(db.scalars(select(Benefit).where(Benefit.employee_id == employee.id)))


@router.post("/{benefit_id}/end", response_model=BenefitOut)
def end_employee_benefit(
    benefit_id: uuid.UUID,
    body: BenefitEnd,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Benefit:
    benefit = db.get(Benefit, benefit_id)
    if benefit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="benefit not found")
    try:
        end_benefit(db, benefit, end_date=body.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="benefit.end",
        entity_type="benefit",
        entity_id=benefit.id,
    )
    return benefit
