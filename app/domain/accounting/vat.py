"""VAT on a customer invoice: how it's treated and at what rate.

The rate an invoice charges is stored on the invoice, so a later change in
the law never alters an invoice already issued. A standard rate is looked up
here by the organisation's country and the invoice's issue date; a rate for
anything else (a customer in another country, a special scheme) is named and
entered by the user as "other".
"""

import enum
from datetime import date

from app.domain.money import apply_rate_ppm

PPM = 1_000_000


class VatTreatment(str, enum.Enum):
    STANDARD = "standard"  # the country's standard rate
    EXEMPT = "exempt"  # an exempt supply: no VAT, and none to account for
    ZERO_RATED = "zero_rated"  # taxable at 0% (exports, for example)
    OTHER = "other"  # a rate the user names and enters


# Standard VAT rates by country, each from the date it took effect, newest
# last. Nigeria: 7.5% under the Value Added Tax Act as amended by the Finance
# Act 2019, in force from 1 February 2020 and kept by the Nigeria Tax Act
# 2025. Confirm against the current Act before adding a country or a change.
STANDARD_VAT_RATES_PPM: dict[str, tuple[tuple[date, int], ...]] = {
    "NG": ((date(2020, 2, 1), 75_000),),
}

TREATMENT_LABELS = {
    VatTreatment.STANDARD: "VAT",
    VatTreatment.EXEMPT: "VAT exempt",
    VatTreatment.ZERO_RATED: "Zero-rated",
}


def standard_vat_rate_ppm(country_code: str, on: date) -> int | None:
    """The country's standard rate on that date, or None if this app doesn't
    hold one for the country (the user then uses "other")."""
    rate = None
    for effective_from, rate_ppm in STANDARD_VAT_RATES_PPM.get(country_code, ()):
        if effective_from <= on:
            rate = rate_ppm
    return rate


def percent_label(rate_ppm: int) -> str:
    """75_000 -> "7.5%", 150_000 -> "15%", 0 -> "0%"."""
    whole, fraction = divmod(rate_ppm, PPM // 100)
    if not fraction:
        return f"{whole}%"
    digits = f"{fraction:04d}".rstrip("0")
    return f"{whole}.{digits}%"


def compute_vat(net_minor: int, rate_ppm: int) -> int:
    """VAT on a net amount, rounded half up to the minor unit."""
    if net_minor < 0:
        raise ValueError("net_minor must not be negative")
    if not 0 <= rate_ppm <= PPM:
        raise ValueError("a VAT rate must be between 0% and 100%")
    return apply_rate_ppm(net_minor, rate_ppm)


def resolve_vat(
    *,
    treatment: VatTreatment | None,
    country_code: str,
    issue_date: date,
    rate_name: str | None,
    rate_ppm: int | None,
) -> tuple[str | None, int]:
    """(the rate's name as printed, rate in ppm) for an invoice. No treatment
    means no VAT charged, as on invoices raised before VAT was recorded."""
    if treatment is None:
        return None, 0
    if treatment is VatTreatment.STANDARD:
        standard = standard_vat_rate_ppm(country_code, issue_date)
        if standard is None:
            raise ValueError(
                f"there's no standard VAT rate on record for {country_code}; "
                "choose Other and enter the rate"
            )
        return f"{TREATMENT_LABELS[treatment]} {percent_label(standard)}", standard
    if treatment in (VatTreatment.EXEMPT, VatTreatment.ZERO_RATED):
        return TREATMENT_LABELS[treatment], 0
    name = (rate_name or "").strip()
    if not name:
        raise ValueError("name the VAT rate (for example 'Ghana VAT 15%')")
    if rate_ppm is None or not 0 <= rate_ppm <= PPM:
        raise ValueError("enter the VAT rate as a percentage between 0 and 100")
    return name, rate_ppm
