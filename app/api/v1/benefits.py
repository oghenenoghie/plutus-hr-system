import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.benefit import Benefit, BenefitDependent, BenefitPlan
from app.models.employee import Employee
from app.models.membership import Role
from app.schemas.benefits import (
    BenefitCreate,
    BenefitDependentCreate,
    BenefitDependentOut,
    BenefitEnd,
    BenefitOut,
    BenefitPlanCreate,
    BenefitPlanOut,
)
from app.services.audit import record_audit_event
from app.services.benefits import add_dependent, assign_benefit, create_benefit_plan, end_benefit

router = APIRouter(prefix="/benefits", tags=["benefits"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT, Role.HR_MANAGER)


@router.post("/plans", response_model=BenefitPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    body: BenefitPlanCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> BenefitPlan:
    try:
        plan = create_benefit_plan(
            db,
            org_id=claims.org_id,
            name=body.name,
            frequency=body.frequency,
            description=body.description,
            default_employee_cost_minor=body.default_employee_cost_minor,
            employer_cost_minor=body.employer_cost_minor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a benefit plan with this name already exists",
        ) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="benefit_plan.create",
        entity_type="benefit_plan",
        entity_id=plan.id,
        metadata={"name": plan.name},
    )
    return plan


@router.get("/plans", response_model=list[BenefitPlanOut])
def list_plans(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[BenefitPlan]:
    return list(db.scalars(select(BenefitPlan).order_by(BenefitPlan.name)))


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

    plan = None
    if body.plan_id is not None:
        plan = db.get(BenefitPlan, body.plan_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="benefit plan not found"
            )

    try:
        benefit = assign_benefit(
            db,
            org_id=claims.org_id,
            employee_id=employee_id,
            effective_date=body.effective_date,
            plan=plan,
            name=body.name,
            frequency=body.frequency,
            description=body.description,
            value_minor=body.value_minor,
            employer_cost_minor=body.employer_cost_minor,
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


@router.post(
    "/employees/{employee_id}/dependents",
    response_model=BenefitDependentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_employee_dependent(
    employee_id: uuid.UUID,
    body: BenefitDependentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> BenefitDependent:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")

    dependent = add_dependent(
        db,
        org_id=claims.org_id,
        employee_id=employee_id,
        full_name=body.full_name,
        relationship=body.relationship,
        date_of_birth=body.date_of_birth,
    )
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="benefit_dependent.add",
        entity_type="benefit_dependent",
        entity_id=dependent.id,
        metadata={"employee_id": str(employee_id)},
    )
    return dependent


@router.get("/employees/{employee_id}/dependents", response_model=list[BenefitDependentOut])
def list_employee_dependents(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[BenefitDependent]:
    return list(
        db.scalars(select(BenefitDependent).where(BenefitDependent.employee_id == employee_id))
    )


@router.get("/me/dependents", response_model=list[BenefitDependentOut])
def list_my_dependents(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[BenefitDependent]:
    return list(
        db.scalars(select(BenefitDependent).where(BenefitDependent.employee_id == employee.id))
    )


@router.delete("/dependents/{dependent_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_dependent(
    dependent_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> None:
    dependent = db.get(BenefitDependent, dependent_id)
    if dependent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dependent not found")
    db.delete(dependent)
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="benefit_dependent.remove",
        entity_type="benefit_dependent",
        entity_id=dependent_id,
    )
