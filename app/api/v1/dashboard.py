from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.schemas.dashboard import OrgSummaryOut
from app.schemas.payroll import PayRunOut
from app.schemas.statutory_liabilities import StatutoryLiabilityOut
from app.services.dashboard import org_summary, upcoming_deadlines

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Read-only for every role that lands here as its home page (homeForRole in
# the frontend sends every non-employee role to /dashboard) or is meant to
# see the Overview nav item — this needs to stay in sync with both.
_VIEW = require_roles(
    Role.ADMIN,
    Role.PAYROLL_MANAGER,
    Role.ACCOUNTANT,
    Role.HR_MANAGER,
    Role.MANAGER,
    Role.DEPARTMENT_MANAGER,
    Role.AUDITOR,
)


@router.get("/summary", response_model=OrgSummaryOut)
def get_org_summary(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW)
) -> OrgSummaryOut:
    summary = org_summary(db, claims.org_id, on=datetime.now(UTC).date())
    last_pay_run = (
        PayRunOut.model_validate(summary.last_completed_pay_run)
        if summary.last_completed_pay_run is not None
        else None
    )
    return OrgSummaryOut(
        active_employee_count=summary.active_employee_count,
        last_completed_pay_run=last_pay_run,
        outstanding_liability_minor=summary.outstanding_liability_minor,
        pending_leave_request_count=summary.pending_leave_request_count,
        pending_expense_count=summary.pending_expense_count,
        expiring_contract_count=summary.expiring_contract_count,
        cash_balance_minor=summary.cash_balance_minor,
        accounts_payable_minor=summary.accounts_payable_minor,
        accounts_receivable_minor=summary.accounts_receivable_minor,
    )


@router.get("/deadlines", response_model=list[StatutoryLiabilityOut])
def get_upcoming_deadlines(
    within_days: int = 30,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
) -> list[StatutoryLiabilityOut]:
    today = datetime.now(UTC).date()
    liabilities = upcoming_deadlines(db, claims.org_id, on=today, within_days=within_days)
    return [StatutoryLiabilityOut.model_validate(liability) for liability in liabilities]
