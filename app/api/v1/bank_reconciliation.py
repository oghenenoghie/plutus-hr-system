import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.ledger_statement_line import LedgerStatementLine
from app.models.membership import Role
from app.schemas.bank_reconciliation import (
    ImportLedgerStatementLinesRequest,
    LedgerReconciliationStatusOut,
    LedgerStatementLineOut,
    MatchLedgerStatementLineRequest,
)
from app.services.ledger_reconciliation import (
    LedgerStatementLineImport,
    import_statement_lines,
    match_statement_line,
    reconciliation_status,
    unmatch_statement_line,
)

router = APIRouter(prefix="/bank-reconciliation", tags=["bank-reconciliation"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_line_or_404(db: Session, line_id: uuid.UUID) -> LedgerStatementLine:
    line = db.get(LedgerStatementLine, line_id)
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="statement line not found"
        )
    return line


@router.post(
    "/statement-lines",
    response_model=list[LedgerStatementLineOut],
    status_code=status.HTTP_201_CREATED,
)
def create_statement_lines(
    body: ImportLedgerStatementLinesRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[LedgerStatementLine]:
    lines = [LedgerStatementLineImport(**line.model_dump()) for line in body.lines]
    return import_statement_lines(
        db, org_id=claims.org_id, account_code=body.account_code, lines=lines
    )


@router.post("/statement-lines/{line_id}/match", response_model=LedgerStatementLineOut)
def match_line(
    line_id: uuid.UUID,
    body: MatchLedgerStatementLineRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> LedgerStatementLine:
    line = _get_line_or_404(db, line_id)
    try:
        return match_statement_line(
            db, line, ledger_entry_id=body.ledger_entry_id, matched_by=claims.account_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/statement-lines/{line_id}/unmatch", response_model=LedgerStatementLineOut)
def unmatch_line(
    line_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> LedgerStatementLine:
    line = _get_line_or_404(db, line_id)
    try:
        return unmatch_statement_line(db, line)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/status", response_model=LedgerReconciliationStatusOut)
def get_reconciliation_status(
    account_code: str,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> LedgerReconciliationStatusOut:
    result = reconciliation_status(db, claims.org_id, account_code)
    return LedgerReconciliationStatusOut.model_validate(result)
