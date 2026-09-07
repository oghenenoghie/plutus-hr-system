import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.budget import Budget
from app.models.membership import Role
from app.schemas.budgets import BudgetCreate, BudgetOut, BudgetVsActualOut
from app.services.budgets import (
    budget_vs_actual,
    create_budget,
    delete_budget,
    get_budget,
    list_budgets,
    update_budget,
)

router = APIRouter(prefix="/budgets", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_budget_or_404(db: Session, budget_id: uuid.UUID) -> Budget:
    budget = db.get(Budget, budget_id)
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="budget not found")
    return budget


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create(
    body: BudgetCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> BudgetOut:
    try:
        return create_budget(
            db,
            org_id=claims.org_id,
            name=body.name,
            department_id=body.department_id,
            period_start=body.period_start,
            period_end=body.period_end,
            lines=body.lines,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a budget with this name already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[BudgetOut])
def list_all(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> list[BudgetOut]:
    return list_budgets(db, org_id=claims.org_id)


@router.get("/{budget_id}", response_model=BudgetOut)
def get(
    budget_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> BudgetOut:
    return get_budget(db, _get_budget_or_404(db, budget_id))


@router.put("/{budget_id}", response_model=BudgetOut)
def update(
    budget_id: uuid.UUID,
    body: BudgetCreate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> BudgetOut:
    budget = _get_budget_or_404(db, budget_id)
    try:
        return update_budget(
            db,
            budget,
            name=body.name,
            department_id=body.department_id,
            period_start=body.period_start,
            period_end=body.period_end,
            lines=body.lines,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a budget with this name already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    budget_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> None:
    delete_budget(db, _get_budget_or_404(db, budget_id))


@router.get("/{budget_id}/actuals", response_model=BudgetVsActualOut)
def actuals(
    budget_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> BudgetVsActualOut:
    return budget_vs_actual(db, _get_budget_or_404(db, budget_id))
