from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.compliance.models import RuleVersion
from app.compliance.resolver import resolve_rule_version
from app.core.deps import get_current_claims
from app.core.security import TokenClaims
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.payslip import compute_payslip
from app.schemas.compliance import PayeEstimateOut, PayeEstimateRequest

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


@router.post("/paye-estimate", response_model=PayeEstimateOut)
def estimate_paye(
    body: PayeEstimateRequest, _claims: TokenClaims = Depends(get_current_claims)
) -> PayeEstimateOut:
    """A standalone what-if: given only an annual gross and annual rent
    (no real employee), assumes a 50/30/20 basic/housing/transport split
    and runs the exact same compute_payslip the real payroll engine uses
    — one full year as a single period, so the result is an annual
    figure, not a monthly slice needing cumulative history. This is
    always an illustration; a real payslip reads an employee's actual
    stored components, never this split.
    """
    if body.annual_gross_minor <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="annual_gross_minor must be positive"
        )
    if body.annual_rent_minor < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="annual_rent_minor must not be negative"
        )

    rules = resolve_rule_version(_COUNTRY, datetime.now(UTC).date())
    basic_minor = body.annual_gross_minor * 50 // 100
    housing_minor = body.annual_gross_minor * 30 // 100
    transport_minor = body.annual_gross_minor - basic_minor - housing_minor

    computation = compute_payslip(
        basic_minor=basic_minor,
        housing_minor=housing_minor,
        transport_minor=transport_minor,
        other_earnings_minor=0,
        annual_rent_paid_minor=body.annual_rent_minor,
        periods_elapsed_this_year=12,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=rules,
    )

    return PayeEstimateOut(
        rule_version_id=rules.id,
        basic_minor=basic_minor,
        housing_minor=housing_minor,
        transport_minor=transport_minor,
        gross_annual_minor=computation.gross_minor,
        pension_employee_annual_minor=computation.pension_employee_minor,
        nhf_annual_minor=computation.nhf_minor,
        rent_relief_annual_minor=computation.cumulative_rent_relief_minor,
        chargeable_income_annual_minor=computation.cumulative_chargeable_income_minor,
        paye_annual_minor=computation.paye_minor,
        paye_monthly_minor=computation.paye_minor // 12,
        net_annual_minor=computation.net_pay_minor,
        net_monthly_minor=computation.net_pay_minor // 12,
    )
