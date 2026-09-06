from app.compliance.models import Band
from app.domain.money import apply_rate_ppm


def compute_chargeable_income(
    annual_gross_minor: int,
    pension_employee_minor: int,
    nhf_minor: int,
    rent_relief_minor: int,
) -> int:
    """chargeable = max(0, gross − pension(EE) − NHF − rent relief).

    This is the only path into compute_paye_annual: callers can't tax gross
    directly, because this function's return value — chargeable income,
    never gross — is the sole input that function accepts.
    """
    for value, name in (
        (annual_gross_minor, "annual_gross_minor"),
        (pension_employee_minor, "pension_employee_minor"),
        (nhf_minor, "nhf_minor"),
        (rent_relief_minor, "rent_relief_minor"),
    ):
        if value < 0:
            raise ValueError(f"{name} must not be negative")
    return max(0, annual_gross_minor - pension_employee_minor - nhf_minor - rent_relief_minor)


def compute_paye_annual(chargeable_income_minor: int, bands: tuple[Band, ...]) -> int:
    """Progressive PAYE on annual chargeable income: each band's rate
    applies only to the slice of income that falls within it."""
    if chargeable_income_minor < 0:
        raise ValueError("chargeable_income_minor must not be negative")
    if chargeable_income_minor == 0:
        return 0

    tax_minor = 0
    previous_ceiling = 0
    remaining = chargeable_income_minor
    for band in bands:
        band_width = remaining if band.up_to_minor is None else band.up_to_minor - previous_ceiling
        taxable_in_band = min(remaining, band_width)
        if taxable_in_band <= 0:
            break
        tax_minor += apply_rate_ppm(taxable_in_band, band.rate_ppm)
        remaining -= taxable_in_band
        if band.up_to_minor is not None:
            previous_ceiling = band.up_to_minor
        if remaining <= 0:
            break
    return tax_minor


def compute_incremental_paye(
    cumulative_chargeable_income_minor: int,
    previously_withheld_minor: int,
    bands: tuple[Band, ...],
) -> int:
    """PAYE due for the current period under cumulative-annual computation:
    tax owed on year-to-date chargeable income, less what's already been
    withheld this year — never a naive monthly slice of the new figure
    (nigeria-statutory-compliance.md §1, §12 mid-year pay change case)."""
    if previously_withheld_minor < 0:
        raise ValueError("previously_withheld_minor must not be negative")
    total_due = compute_paye_annual(cumulative_chargeable_income_minor, bands)
    return max(0, total_due - previously_withheld_minor)
