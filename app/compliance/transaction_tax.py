"""Jurisdiction-neutral indirect-tax calculation primitives.
Rates use parts per million (1_000_000 = 100%); money uses integer minor units.
This module does not post to the ledger or replace the existing Nigeria payroll path.
Only ACTIVE, effective-dated rule packs may calculate. Country packs remain release-gated.
"""
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.compliance.multicountry import TaxConfigurationError, get_country_profile

PPM = 1_000_000


class IndirectTaxRuleStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACTIVE = "active"
    RETIRED = "retired"


class TaxTreatment(StrEnum):
    STANDARD = "standard"
    ZERO_RATED = "zero_rated"
    EXEMPT = "exempt"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class IndirectTaxComponent:
    code: str
    name: str
    rate_ppm: int
    compound_on_previous: bool = False

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.name.strip():
            raise ValueError("component code and name are required")
        if not 0 <= self.rate_ppm <= PPM:
            raise ValueError("rate_ppm must be between 0 and 1,000,000")


@dataclass(frozen=True, slots=True)
class IndirectTaxRulePack:
    id: str
    country: str
    tax_type: str
    effective_from: date
    effective_to: date | None
    status: IndirectTaxRuleStatus
    components: tuple[IndirectTaxComponent, ...]
    source_reference: str
    approved_by: str | None = None

    def __post_init__(self) -> None:
        profile = get_country_profile(self.country)
        if not self.id.strip() or not self.tax_type.strip():
            raise ValueError("rule pack id and tax_type are required")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        if not self.source_reference.strip():
            raise ValueError("source_reference is required")
        if not self.components:
            raise ValueError("at least one tax component is required")
        codes = [component.code for component in self.components]
        if len(codes) != len(set(codes)):
            raise ValueError("component codes must be unique within a rule pack")
        if self.status is IndirectTaxRuleStatus.ACTIVE and not (self.approved_by or "").strip():
            raise ValueError("an active rule pack requires approved_by")
        object.__setattr__(self, "country", profile.code)
        object.__setattr__(self, "tax_type", self.tax_type.lower())

    def applies_on(self, on: date) -> bool:
        return self.effective_from <= on and (
            self.effective_to is None or on < self.effective_to
        )


@dataclass(frozen=True, slots=True)
class IndirectTaxLine:
    code: str
    name: str
    rate_ppm: int
    base_minor: int
    amount_minor: int


@dataclass(frozen=True, slots=True)
class IndirectTaxResult:
    country: str
    currency: str
    tax_type: str
    treatment: TaxTreatment
    inclusive: bool
    net_base_minor: int
    component_lines: tuple[IndirectTaxLine, ...]
    total_tax_minor: int
    total_minor: int
    rule_pack_id: str
    source_reference: str
    effective_date: date


def _round_half_up(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (2 * numerator + denominator) // (2 * denominator)


def calculate_indirect_tax(
    *,
    country: str,
    tax_type: str,
    amount_minor: int,
    rule_pack: IndirectTaxRulePack,
    on: date,
    treatment: TaxTreatment = TaxTreatment.STANDARD,
    inclusive: bool = False,
) -> IndirectTaxResult:
    """Calculate component-level indirect tax without accounting posting.

    Inclusive prices with multiple standard-rated components are rejected
    until the jurisdiction's allocation and rounding policy is explicitly
    modelled. This avoids silently guessing legal calculation order.
    """
    profile = get_country_profile(country)
    if amount_minor < 0:
        raise ValueError("amount_minor must not be negative")
    if rule_pack.country != profile.code or rule_pack.tax_type != tax_type.lower():
        raise TaxConfigurationError("Rule pack does not match requested country/tax type")
    if rule_pack.status is not IndirectTaxRuleStatus.ACTIVE:
        raise TaxConfigurationError("Draft or unapproved tax rules cannot be used for calculation")
    if not rule_pack.applies_on(on):
        raise TaxConfigurationError(f"No active rule pack applies on {on.isoformat()}")
    if inclusive and len(rule_pack.components) > 1 and treatment is TaxTreatment.STANDARD:
        raise TaxConfigurationError(
            "Inclusive calculation with multiple components requires a verified "
            "jurisdiction-specific allocation and rounding policy"
        )

    if treatment is not TaxTreatment.STANDARD:
        lines = tuple(
            IndirectTaxLine(c.code, c.name, c.rate_ppm, amount_minor, 0)
            for c in rule_pack.components
        )
        return IndirectTaxResult(
            profile.code, profile.currency, tax_type.lower(), treatment, inclusive,
            amount_minor, lines, 0, amount_minor, rule_pack.id, rule_pack.source_reference, on,
        )

    if inclusive:
        component = rule_pack.components[0]
        denominator = PPM + component.rate_ppm
        tax = _round_half_up(amount_minor * component.rate_ppm, denominator)
        net = amount_minor - tax
        lines = (IndirectTaxLine(component.code, component.name, component.rate_ppm, net, tax),)
        total_tax, total = tax, amount_minor
    else:
        net = amount_minor
        accumulated_tax = 0
        result_lines = []
        for component in rule_pack.components:
            base = net + accumulated_tax if component.compound_on_previous else net
            tax = _round_half_up(base * component.rate_ppm, PPM)
            result_lines.append(
                IndirectTaxLine(component.code, component.name, component.rate_ppm, base, tax)
            )
            accumulated_tax += tax
        lines = tuple(result_lines)
        total_tax, total = accumulated_tax, net + accumulated_tax

    return IndirectTaxResult(
        country=profile.code, currency=profile.currency, tax_type=tax_type.lower(),
        treatment=treatment, inclusive=inclusive, net_base_minor=net,
        component_lines=lines, total_tax_minor=total_tax, total_minor=total,
        rule_pack_id=rule_pack.id, source_reference=rule_pack.source_reference,
        effective_date=on,
    )
