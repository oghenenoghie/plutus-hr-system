from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.compliance.models import RuleVersion
from app.compliance.resolver import resolve_rule_version
from app.core.deps import get_current_claims
from app.core.security import TokenClaims

router = APIRouter(prefix="/compliance", tags=["compliance"])

_COUNTRY = "NG"  # same single-country assumption as app.services.payroll


@router.get("/current-rules", response_model=RuleVersion)
def get_current_rules(_claims: TokenClaims = Depends(get_current_claims)) -> RuleVersion:
    """The rule version in force today — every base/rate/authority/deadline
    the compliance engine actually computes from, read straight from the
    same resolver process_employee_payslip uses. Never a second copy of
    these figures: a screen showing statutory rates must read this, not
    hardcode them."""
    return resolve_rule_version(_COUNTRY, datetime.now(UTC).date())
