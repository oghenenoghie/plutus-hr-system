from app.compliance.models import WhtRule
from app.domain.money import apply_rate_ppm


def compute_wht(payment_minor: int, category: str, rule: WhtRule) -> int:
    """Withholding tax on a contractor/vendor payment, resolved by service
    category — never a flat rate (nigeria-statutory-compliance.md §8)."""
    if payment_minor < 0:
        raise ValueError("payment_minor must not be negative")
    return apply_rate_ppm(payment_minor, rule.rate_for(category))
