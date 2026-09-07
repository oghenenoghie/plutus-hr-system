from app.compliance.models import PayeRule
from app.domain.money import apply_rate_ppm


def compute_rent_relief(annual_rent_paid_minor: int, rule: PayeRule) -> int:
    """20% of annual rent paid, capped — applied before chargeable income
    is computed, never after PAYE banding (nigeria-statutory-compliance.md §1)."""
    if annual_rent_paid_minor < 0:
        raise ValueError("annual_rent_paid_minor must not be negative")
    uncapped = apply_rate_ppm(annual_rent_paid_minor, rule.rent_relief_rate_ppm)
    return min(uncapped, rule.rent_relief_cap_minor)
