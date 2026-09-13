import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.approval import ApprovalRequestType
from app.models.employee import Employee
from app.models.expense import Expense
from app.models.membership import Role
from app.schemas.approvals import DecisionBody
from app.schemas.expenses import ExpenseCreate, ExpenseOut
from app.services import approvals
from app.services.audit import record_audit_event
from app.services.expenses import decide_expense, mark_expense_reimbursed, submit_expense

router = APIRouter(prefix="/expenses", tags=["expenses"])

_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)
_REIMBURSE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_or_404(db: Session, expense_id: uuid.UUID) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="expense not found")
    return expense


@router.post("/me", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def submit_my_expense(
    body: ExpenseCreate,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
    claims: TokenClaims = Depends(get_current_claims),
) -> Expense:
    try:
        expense = submit_expense(
            db,
            org_id=employee.org_id,
            employee_id=employee.id,
            category=body.category,
            description=body.description,
            amount_minor=body.amount_minor,
            expense_date=body.expense_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    approvals.get_or_create_instance(
        db,
        org_id=employee.org_id,
        request_type=ApprovalRequestType.EXPENSE,
        request_id=expense.id,
        requester_employee_id=employee.id,
    )
    record_audit_event(
        db,
        org_id=employee.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="expense.submit",
        entity_type="expense",
        entity_id=expense.id,
        metadata={"amount_minor": expense.amount_minor, "category": expense.category},
    )
    return expense


@router.get("/me", response_model=list[ExpenseOut])
def list_my_expenses(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[Expense]:
    return list(
        db.scalars(
            select(Expense)
            .where(Expense.employee_id == employee.id)
            .order_by(Expense.expense_date.desc())
        )
    )


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[Expense]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return list(db.scalars(select(Expense)))

    manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if manager is None:
        return []
    report_ids = select(Employee.id).where(Employee.manager_id == manager.id)
    return list(db.scalars(select(Expense).where(Expense.employee_id.in_(report_ids))))


@router.post("/{expense_id}/approve", response_model=ExpenseOut)
def approve_expense(
    expense_id: uuid.UUID,
    body: DecisionBody | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Expense:
    expense = _get_or_404(db, expense_id)
    try:
        _, is_final = approvals.decide(
            db,
            claims=claims,
            request_type=ApprovalRequestType.EXPENSE,
            request_id=expense.id,
            requester_employee_id=expense.employee_id,
            approve=True,
            comment=body.comment if body else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if is_final:
        try:
            decide_expense(db, expense, approve=True)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="expense.approve" if is_final else "expense.approve_step",
        entity_type="expense",
        entity_id=expense.id,
    )
    return expense


@router.post("/{expense_id}/reject", response_model=ExpenseOut)
def reject_expense(
    expense_id: uuid.UUID,
    body: DecisionBody | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Expense:
    expense = _get_or_404(db, expense_id)
    try:
        approvals.decide(
            db,
            claims=claims,
            request_type=ApprovalRequestType.EXPENSE,
            request_id=expense.id,
            requester_employee_id=expense.employee_id,
            approve=False,
            comment=body.comment if body else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        decide_expense(db, expense, approve=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="expense.reject",
        entity_type="expense",
        entity_id=expense.id,
    )
    return expense


@router.post("/{expense_id}/reimburse", response_model=ExpenseOut)
def reimburse_expense(
    expense_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_REIMBURSE),
) -> Expense:
    expense = _get_or_404(db, expense_id)
    try:
        mark_expense_reimbursed(db, expense)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="expense.reimburse",
        entity_type="expense",
        entity_id=expense.id,
        metadata={"amount_minor": expense.amount_minor},
    )
    return expense
