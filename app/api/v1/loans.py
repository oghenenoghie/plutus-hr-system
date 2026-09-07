import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.loan import Loan
from app.models.membership import Role
from app.schemas.loans import LoanCreate, LoanOut
from app.services.audit import record_audit_event
from app.services.loans import ActiveLoanExistsError, cancel_loan, request_loan
from app.services.payroll import outstanding_loan_balance

router = APIRouter(prefix="/loans", tags=["loans"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _to_out(db: Session, loan: Loan) -> LoanOut:
    return LoanOut(
        id=loan.id,
        employee_id=loan.employee_id,
        principal_minor=loan.principal_minor,
        num_installments=loan.num_installments,
        installment_minor=loan.installment_minor,
        start_date=loan.start_date,
        status=loan.status,
        outstanding_minor=outstanding_loan_balance(db, loan),
        created_at=loan.created_at,
    )


def _get_loan_or_404(db: Session, loan_id: uuid.UUID) -> Loan:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="loan not found")
    return loan


@router.post("/me", response_model=LoanOut, status_code=status.HTTP_201_CREATED)
def request_my_loan(
    body: LoanCreate,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
    claims: TokenClaims = Depends(get_current_claims),
) -> LoanOut:
    try:
        loan = request_loan(
            db,
            org_id=employee.org_id,
            employee_id=employee.id,
            principal_minor=body.principal_minor,
            num_installments=body.num_installments,
            start_date=body.start_date,
        )
    except (ActiveLoanExistsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=employee.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="loan.request",
        entity_type="loan",
        entity_id=loan.id,
        metadata={"principal_minor": loan.principal_minor},
    )
    return _to_out(db, loan)


@router.get("/me", response_model=list[LoanOut])
def list_my_loans(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[LoanOut]:
    loans = db.scalars(select(Loan).where(Loan.employee_id == employee.id))
    return [_to_out(db, loan) for loan in loans]


@router.get("", response_model=list[LoanOut])
def list_loans(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[LoanOut]:
    loans = db.scalars(select(Loan))
    return [_to_out(db, loan) for loan in loans]


@router.get("/{loan_id}", response_model=LoanOut)
def get_loan(
    loan_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> LoanOut:
    return _to_out(db, _get_loan_or_404(db, loan_id))


@router.post("/{loan_id}/cancel", response_model=LoanOut)
def cancel_loan_endpoint(
    loan_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> LoanOut:
    loan = _get_loan_or_404(db, loan_id)
    try:
        cancel_loan(db, loan)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="loan.cancel",
        entity_type="loan",
        entity_id=loan.id,
    )
    return _to_out(db, loan)
