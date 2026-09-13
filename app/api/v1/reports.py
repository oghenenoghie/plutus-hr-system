from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.schemas.reports import AgingLineOut, PayrollCostLineOut
from app.services.reports import ap_aging_report, ar_aging_report, payroll_cost_by_department

router = APIRouter(prefix="/reports", tags=["reports"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.get("/payroll-cost", response_model=list[PayrollCostLineOut])
def get_payroll_cost_by_department(
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[PayrollCostLineOut]:
    lines = payroll_cost_by_department(db, claims.org_id, from_date=from_date, to_date=to_date)
    return [PayrollCostLineOut(**vars(line)) for line in lines]


@router.get("/ap-aging", response_model=list[AgingLineOut])
def get_ap_aging(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[AgingLineOut]:
    lines = ap_aging_report(db, claims.org_id, as_of=as_of or datetime.now(UTC).date())
    return [AgingLineOut(**vars(line)) for line in lines]


@router.get("/ar-aging", response_model=list[AgingLineOut])
def get_ar_aging(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[AgingLineOut]:
    lines = ar_aging_report(db, claims.org_id, as_of=as_of or datetime.now(UTC).date())
    return [AgingLineOut(**vars(line)) for line in lines]
