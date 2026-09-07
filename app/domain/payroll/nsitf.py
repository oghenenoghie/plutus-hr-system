from app.compliance.models import NsitfRule
from app.domain.money import apply_rate_ppm


def compute_nsitf(total_monthly_payroll_minor: int, rule: NsitfRule) -> int:
    """Employer-borne, 1% of total monthly payroll. The caller must pass a
    base that already excludes pension contributions, bonuses, overtime,
    and one-off payments like 13th-month income — this function has no way
    to derive that exclusion from a gross figure and will misapply the rate
    if handed the wrong base (nigeria-statutory-compliance.md §6)."""
    if total_monthly_payroll_minor < 0:
        raise ValueError("total_monthly_payroll_minor must not be negative")
    return apply_rate_ppm(total_monthly_payroll_minor, rule.rate_ppm)
