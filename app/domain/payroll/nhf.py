from app.compliance.models import NhfRule
from app.domain.money import apply_rate_ppm


def compute_nhf(basic_salary_minor: int, rule: NhfRule) -> int:
    """NHF is levied on basic salary only — never on gross or on the full
    pensionable base (nigeria-statutory-compliance.md §4)."""
    if basic_salary_minor < 0:
        raise ValueError("basic_salary_minor must not be negative")
    return apply_rate_ppm(basic_salary_minor, rule.rate_ppm)
