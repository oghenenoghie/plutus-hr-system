import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.employee_checklist_item import EmployeeChecklistItem
from app.models.membership import Role
from app.schemas.employee_checklists import ChecklistItemCreate, ChecklistItemOut
from app.services.employee_checklists import add_checklist_item, complete_checklist_item

router = APIRouter(prefix="/employees", tags=["employee-checklists"])

# Not exposed to self-service, same as DisciplinaryCase: onboarding/
# offboarding tasks are an HR/admin concern, never something an employee or
# their manager views or edits directly.
_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_employee_or_404(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    return employee


def _get_item_or_404(db: Session, item_id: uuid.UUID) -> EmployeeChecklistItem:
    item = db.get(EmployeeChecklistItem, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="checklist item not found"
        )
    return item


@router.post(
    "/{employee_id}/checklist-items",
    response_model=ChecklistItemOut,
    status_code=status.HTTP_201_CREATED,
)
def create_checklist_item(
    employee_id: uuid.UUID,
    body: ChecklistItemCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EmployeeChecklistItem:
    _get_employee_or_404(db, employee_id)
    return add_checklist_item(
        db, org_id=claims.org_id, employee_id=employee_id, **body.model_dump()
    )


@router.get("/{employee_id}/checklist-items", response_model=list[ChecklistItemOut])
def list_checklist_items(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[EmployeeChecklistItem]:
    _get_employee_or_404(db, employee_id)
    return list(
        db.scalars(
            select(EmployeeChecklistItem)
            .where(EmployeeChecklistItem.employee_id == employee_id)
            .order_by(EmployeeChecklistItem.created_at)
        )
    )


@router.post("/checklist-items/{item_id}/complete", response_model=ChecklistItemOut)
def complete_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EmployeeChecklistItem:
    item = _get_item_or_404(db, item_id)
    try:
        complete_checklist_item(db, item, completed_by=claims.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return item
