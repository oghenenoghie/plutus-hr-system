import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.final_settlement import FinalSettlement
from app.models.membership import Role
from app.schemas.final_settlement import FinalSettlementCreate, FinalSettlementOut
from app.services.final_settlement import process_final_settlement

router = APIRouter(prefix="/final-settlements", tags=["final-settlement"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.post(
    "/{employee_id}", response_model=FinalSettlementOut, status_code=status.HTTP_201_CREATED
)
def process_settlement(
    employee_id: uuid.UUID,
    body: FinalSettlementCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FinalSettlement:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")

    try:
        return process_final_settlement(
            db,
            org_id=claims.org_id,
            employee=employee,
            termination_date=body.termination_date,
            gratuity_minor=body.gratuity_minor,
            leave_days_paid_out=body.leave_days_paid_out,
            leave_payout_minor=body.leave_payout_minor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{employee_id}", response_model=list[FinalSettlementOut])
def list_settlements_for_employee(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[FinalSettlement]:
    return list(
        db.scalars(select(FinalSettlement).where(FinalSettlement.employee_id == employee_id))
    )
