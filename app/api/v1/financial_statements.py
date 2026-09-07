from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.schemas.financial_statements import BalanceSheetOut, IncomeStatementOut
from app.services.financial_statements import balance_sheet, income_statement

router = APIRouter(prefix="/financial-statements", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.get("/balance-sheet", response_model=BalanceSheetOut)
def get_balance_sheet(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> BalanceSheetOut:
    return balance_sheet(db, org_id=claims.org_id, as_of=as_of)


@router.get("/income-statement", response_model=IncomeStatementOut)
def get_income_statement(
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> IncomeStatementOut:
    return income_statement(db, org_id=claims.org_id, from_date=from_date, to_date=to_date)
