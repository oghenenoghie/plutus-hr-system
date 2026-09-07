import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.bank_statement_line import BankStatementLine
from app.models.company_bank_account import CompanyBankAccount
from app.models.membership import Role
from app.schemas.bank_reconciliation import (
    BankStatementLineCreate,
    BankStatementLineMatch,
    BankStatementLineOut,
    CompanyBankAccountCreate,
    CompanyBankAccountOut,
    ReconciliationSummaryOut,
)
from app.services.bank_reconciliation import (
    create_statement_line,
    list_statement_lines,
    match_line,
    reconciliation_summary,
    unmatch_line,
)
from app.services.company_bank_accounts import (
    list_company_bank_accounts,
    register_company_bank_account,
)

router = APIRouter(prefix="/company-bank-accounts", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_bank_account_or_404(db: Session, bank_account_id: uuid.UUID) -> CompanyBankAccount:
    bank_account = db.get(CompanyBankAccount, bank_account_id)
    if bank_account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bank account not found")
    return bank_account


def _get_statement_line_or_404(
    db: Session, bank_account: CompanyBankAccount, line_id: uuid.UUID
) -> BankStatementLine:
    line = db.get(BankStatementLine, line_id)
    if line is None or line.bank_account_id != bank_account.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="statement line not found"
        )
    return line


@router.post("", response_model=CompanyBankAccountOut, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    body: CompanyBankAccountCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> CompanyBankAccount:
    try:
        return register_company_bank_account(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a bank account with this number already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[CompanyBankAccountOut])
def list_bank_accounts(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> list[CompanyBankAccount]:
    return list_company_bank_accounts(db, org_id=claims.org_id)


@router.get("/{bank_account_id}", response_model=CompanyBankAccountOut)
def get_bank_account(
    bank_account_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> CompanyBankAccount:
    return _get_bank_account_or_404(db, bank_account_id)


@router.post(
    "/{bank_account_id}/statement-lines",
    response_model=BankStatementLineOut,
    status_code=status.HTTP_201_CREATED,
)
def create_line(
    bank_account_id: uuid.UUID,
    body: BankStatementLineCreate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> BankStatementLine:
    bank_account = _get_bank_account_or_404(db, bank_account_id)
    try:
        return create_statement_line(db, bank_account, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{bank_account_id}/statement-lines", response_model=list[BankStatementLineOut])
def get_lines(
    bank_account_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[BankStatementLine]:
    bank_account = _get_bank_account_or_404(db, bank_account_id)
    return list_statement_lines(db, bank_account)


@router.post(
    "/{bank_account_id}/statement-lines/{line_id}/match", response_model=BankStatementLineOut
)
def match(
    bank_account_id: uuid.UUID,
    line_id: uuid.UUID,
    body: BankStatementLineMatch,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> BankStatementLine:
    bank_account = _get_bank_account_or_404(db, bank_account_id)
    line = _get_statement_line_or_404(db, bank_account, line_id)
    try:
        return match_line(db, line, bank_account, ledger_entry_id=body.ledger_entry_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="this ledger entry is already matched to another statement line",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{bank_account_id}/statement-lines/{line_id}/unmatch", response_model=BankStatementLineOut
)
def unmatch(
    bank_account_id: uuid.UUID,
    line_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> BankStatementLine:
    bank_account = _get_bank_account_or_404(db, bank_account_id)
    line = _get_statement_line_or_404(db, bank_account, line_id)
    return unmatch_line(db, line)


@router.get("/{bank_account_id}/reconciliation", response_model=ReconciliationSummaryOut)
def get_reconciliation(
    bank_account_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> ReconciliationSummaryOut:
    bank_account = _get_bank_account_or_404(db, bank_account_id)
    return reconciliation_summary(db, bank_account)
