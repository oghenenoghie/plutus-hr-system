from app.compliance.models import ItfRule
from app.domain.money import apply_rate_ppm


def compute_itf(annual_payroll_minor: int, rule: ItfRule, *, qualifies: bool) -> int:
    """1% of annual payroll for qualifying employers, employer-borne.

    `qualifies` must be decided by the caller against a current, confirmed
    headcount/turnover test — this engine does not encode the reference's
    unverified threshold and will never silently decide who owes ITF
    (nigeria-statutory-compliance.md §7).
    """
    if annual_payroll_minor < 0:
        raise ValueError("annual_payroll_minor must not be negative")
    if not qualifies:
        return 0
    return apply_rate_ppm(annual_payroll_minor, rule.rate_ppm)
