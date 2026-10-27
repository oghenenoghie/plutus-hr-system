"""The country catalogue for the multi-country roadmap, and its fail-closed
guard.

Nigeria keeps running on the RuleVersion path (app.compliance.versions). The
other five are ACTIVE for payroll: their rules were approved by Plutus
Technologies from the drafts in docs/countries/, without a local tax
adviser's review, and are encoded in app/compliance/engine/countries/ with
each organisation entering the figures the sources didn't settle (Tax
Settings). Their VAT and other transaction taxes aren't approved: the engine's
indirect-tax registry is empty, so those still fail closed. See
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
    country's tax adviser. ACTIVE: approved and encoded, as a Nigerian rule
    version or an engine rule set.
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
    CountryProfile("GM", "The Gambia", "GMD", "Gambia Revenue Authority", TaxStatus.ACTIVE),
    CountryProfile("RW", "Rwanda", "RWF", "Rwanda Revenue Authority", TaxStatus.ACTIVE),
    CountryProfile("KE", "Kenya", "KES", "Kenya Revenue Authority", TaxStatus.ACTIVE),
    CountryProfile("GH", "Ghana", "GHS", "Ghana Revenue Authority", TaxStatus.ACTIVE),
    CountryProfile("CI", "Côte d'Ivoire", "XOF", "Direction Générale des Impôts", TaxStatus.ACTIVE),
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
