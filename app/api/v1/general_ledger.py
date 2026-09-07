import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.schemas.general_ledger import JournalEntryCreate, LedgerEntryOut, TrialBalanceLine
from app.services.general_ledger import (
    list_ledger_entries,
    post_manual_journal_entry,
    trial_balance,
)

router = APIRouter(prefix="/general-ledger", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.get("/entries", response_model=list[LedgerEntryOut])
def get_ledger_entries(
    account: str | None = None,
    pay_run_id: uuid.UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[LedgerEntryOut]:
    return list_ledger_entries(
        db,
        org_id=claims.org_id,
        account=account,
        pay_run_id=pay_run_id,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/trial-balance", response_model=list[TrialBalanceLine])
def get_trial_balance(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> list[TrialBalanceLine]:
    return trial_balance(db, org_id=claims.org_id)


@router.post(
    "/journal-entries", response_model=list[LedgerEntryOut], status_code=status.HTTP_201_CREATED
)
def create_journal_entry(
    body: JournalEntryCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[LedgerEntryOut]:
    try:
        return post_manual_journal_entry(
            db, org_id=claims.org_id, description=body.description, lines=body.lines
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
