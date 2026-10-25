"""Jurisdiction-neutral tax primitives for the multi-country roadmap.

Nigeria keeps running on the RuleVersion path (app.compliance.versions); this
module only catalogues the other countries and provides the effective-dated
rate and percentage-tax primitives a future, persisted rule store will feed.
No statutory rate for a new country is shipped here: every one of them stays
CONFIGURATION_REQUIRED, and require_configured_country refuses it, until its
rules are sourced from the tax authority, reviewed and approved. See
docs/architecture/multicountry-tax.md.

Money is integer minor units and rates are parts-per-million, as in the rest
of the compliance engine.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.domain.money import apply_rate_ppm

_PPM = 1_000_000


class TaxConfigurationError(ValueError):
    """Raised when a tax calculation is attempted without an approved rule."""


class TaxStatus(StrEnum):
    """How far a country's rules have got. Only ACTIVE is ever used to
    calculate, post or file; every other state is refused.

    CONFIGURATION_REQUIRED: nothing drafted yet. DRAFT: rules drafted from
    official sources (docs/countries/), not yet reviewed. IN_REVIEW: with the
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
    CountryProfile("GM", "The Gambia", "GMD", "Gambia Revenue Authority"),
    CountryProfile("RW", "Rwanda", "RWF", "Rwanda Revenue Authority"),
    CountryProfile("KE", "Kenya", "KES", "Kenya Revenue Authority"),
    CountryProfile("GH", "Ghana", "GHS", "Ghana Revenue Authority"),
    CountryProfile("CI", "Côte d'Ivoire", "XOF", "Direction Générale des Impôts"),
)


def get_country_profile(country_code: str) -> CountryProfile:
    normalized = country_code.strip().upper()
    for profile in COUNTRY_PROFILES:
        if profile.code == normalized:
            return profile
    raise ValueError(f"Unsupported country code: {country_code!r}")


@dataclass(frozen=True, slots=True)
class EffectiveRate:
    """An approved tax rate in force from effective_from up to, but not
    including, effective_to — the same window RuleVersion uses.

    rate_ppm uses 1,000,000 = 100%. source_reference identifies the official
    publication the rate came from; approved_by is the approver's audit
    identity.
    """

    country: str
    tax_type: str
    rate_ppm: int
    effective_from: date
    effective_to: date | None
    rule_version: str
    source_reference: str
    approved_by: str

    def __post_init__(self) -> None:
        if not 0 <= self.rate_ppm <= _PPM:
            raise ValueError("rate_ppm must be between 0 and 1,000,000")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        required = (self.rule_version, self.source_reference, self.approved_by)
        if any(not value.strip() for value in required):
            raise ValueError("rule_version, source_reference and approved_by are required")

    def applies_on(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on < self.effective_to)


@dataclass(frozen=True, slots=True)
class TaxCalculation:
    country: str
    tax_type: str
    taxable_base_minor: int
    tax_minor: int
    total_minor: int
    currency: str
    rule_version: str
    effective_date: date


def calculate_percentage_tax(
    *,
    country: str,
    tax_type: str,
    taxable_base_minor: int,
    rate: EffectiveRate,
    on: date,
    inclusive: bool = False,
) -> TaxCalculation:
    """A percentage tax on an integer minor-unit amount, rounded half-up.

    Tax-exclusive: taxable_base_minor is the net amount and tax is added on
    top. Tax-inclusive: taxable_base_minor is the gross amount and the tax
    is extracted from it, so total_minor is the amount given.
    """
    profile = get_country_profile(country)
    if taxable_base_minor < 0:
        raise ValueError("taxable_base_minor must not be negative")
    if rate.country.upper() != profile.code or rate.tax_type.lower() != tax_type.lower():
        raise TaxConfigurationError(
            "The approved rate does not match the requested country/tax type"
        )
    if not rate.applies_on(on):
        raise TaxConfigurationError(
            f"No effective approved rate for {profile.code}/{tax_type} on {on}"
        )

    if inclusive:
        # gross * rate / (1 + rate), half-up in integers: floor((2n + d) / 2d).
        denominator = _PPM + rate.rate_ppm
        tax_minor = (2 * taxable_base_minor * rate.rate_ppm + denominator) // (2 * denominator)
        base_minor = taxable_base_minor - tax_minor
        total_minor = taxable_base_minor
    else:
        tax_minor = apply_rate_ppm(taxable_base_minor, rate.rate_ppm)
        base_minor = taxable_base_minor
        total_minor = taxable_base_minor + tax_minor

    return TaxCalculation(
        country=profile.code,
        tax_type=tax_type.lower(),
        taxable_base_minor=base_minor,
        tax_minor=tax_minor,
        total_minor=total_minor,
        currency=profile.currency,
        rule_version=rate.rule_version,
        effective_date=on,
    )


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
