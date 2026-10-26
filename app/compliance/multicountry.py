"""The country catalogue for the multi-country roadmap, and its fail-closed
guard.

Nigeria keeps running on the RuleVersion path (app.compliance.versions). The
other five are DRAFT: their rules are drafted, with sources, in
docs/countries/ and await review by each country's tax adviser.
require_configured_country refuses them until their rules are approved and
encoded. The country-neutral calculations (payroll, and VAT and other
transaction taxes) are in app.compliance.engine. See
docs/architecture/multicountry-tax.md.
"""

from dataclasses import dataclass
from enum import StrEnum


class TaxConfigurationError(ValueError):
    """Raised when a tax calculation is attempted without an approved rule."""


class TaxStatus(StrEnum):
    """How far a country's rules have got. Only ACTIVE is ever used to
    calculate, post or file; every other state is refused.

    CONFIGURATION_REQUIRED: nothing drafted yet. DRAFT: rules drafted with
    their sources (docs/countries/), not yet reviewed. IN_REVIEW: with the
    country's tax adviser. ACTIVE: approved and encoded as a rule version.
    """

    ACTIVE = "active"
    IN_REVIEW = "in_review"
    DRAFT = "draft"
    CONFIGURATION_REQUIRED = "configuration_required"


@dataclass(frozen=True, slots=True)
class CountryProfile:
    code: str
    name: str
    currency: str
    tax_authority: str
    status: TaxStatus = TaxStatus.CONFIGURATION_REQUIRED
    enabled_modules: tuple[str, ...] = (
        "vat",
        "withholding_tax",
        "corporate_tax",
        "employment_tax",
    )


COUNTRY_PROFILES: tuple[CountryProfile, ...] = (
    CountryProfile(
        "NG",
        "Nigeria",
        "NGN",
        "Nigeria Revenue Service / relevant state tax authorities",
        TaxStatus.ACTIVE,
    ),
    CountryProfile("GM", "The Gambia", "GMD", "Gambia Revenue Authority", TaxStatus.DRAFT),
    CountryProfile("RW", "Rwanda", "RWF", "Rwanda Revenue Authority", TaxStatus.DRAFT),
    CountryProfile("KE", "Kenya", "KES", "Kenya Revenue Authority", TaxStatus.DRAFT),
    CountryProfile("GH", "Ghana", "GHS", "Ghana Revenue Authority", TaxStatus.DRAFT),
    CountryProfile("CI", "Côte d'Ivoire", "XOF", "Direction Générale des Impôts", TaxStatus.DRAFT),
)


def get_country_profile(country_code: str) -> CountryProfile:
    normalized = country_code.strip().upper()
    for profile in COUNTRY_PROFILES:
        if profile.code == normalized:
            return profile
    raise ValueError(f"Unsupported country code: {country_code!r}")


def require_configured_country(country_code: str, *, tax_type: str) -> CountryProfile:
    """Fail closed for any country whose rules have not been approved."""
    profile = get_country_profile(country_code)
    if profile.status is not TaxStatus.ACTIVE:
        raise TaxConfigurationError(
            f"{profile.name} {tax_type} rules are not production-enabled. Configure and approve "
            "effective-dated rules against official authority guidance before calculating or "
            "posting."
        )
    return profile
