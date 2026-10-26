"""Transaction taxes (VAT and similar): one country's components for one tax
type and effective-dated window, and the pure calculation over them.

A sale or purchase can carry several components, each itemised: for example
a VAT and levies charged alongside it. A component is charged on the net
amount, or, where it compounds, on the net amount plus the components before
it. A supply can also be zero-rated, exempt or out of scope. Whether a
supply is taxable, and how, is the caller's decision from the transaction;
this only does the arithmetic.

Rule sets carry the same status, approval and sources as payroll rule sets
(app.compliance.engine.rules), and app.compliance.engine.registry hands out
only those that pass the same release gate. No country's rates are encoded.
Built on the design proposed in PR #62 (feat/multicountry-indirect-tax-engine).
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.compliance.engine.rounding import round_ratio
from app.compliance.engine.rules import (
    PPM,
    Approval,
    Rounding,
    RuleSetError,
    RuleSetStatus,
    SourceReference,
    approval_problems,
    source_problems,
)
from app.compliance.multicountry import TaxConfigurationError, get_country_profile


class TaxTreatment(StrEnum):
    STANDARD = "standard"
    ZERO_RATED = "zero_rated"
    EXEMPT = "exempt"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class IndirectTaxComponent:
    code: str  # e.g. "VAT"
    name: str
    rate_ppm: int
    source: str  # the SourceReference id it comes from
    liability_account: str
    compound_on_previous: bool = False  # charged on the net plus the earlier components


@dataclass(frozen=True, slots=True)
class IndirectTaxRuleSet:
    """A country's components for one tax type, in force from effective_from
    up to, but not including, effective_to."""

    id: str  # e.g. "GH-VAT-2026.1"
    country: str
    currency: str
    tax_type: str  # lower case, e.g. "vat"
    effective_from: date
    effective_to: date | None
    status: RuleSetStatus
    approval: Approval
    sources: tuple[SourceReference, ...]
    components: tuple[IndirectTaxComponent, ...]
    rounding: Rounding  # applied to each component's amount

    def applies_on(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on < self.effective_to)

    def cited_sources(self) -> tuple[str, ...]:
        return tuple(component.source for component in self.components)


def indirect_structural_problems(rule_set: IndirectTaxRuleSet) -> list[str]:
    problems: list[str] = []
    if not rule_set.id.strip():
        problems.append("the rule set needs an id")
    try:
        profile = get_country_profile(rule_set.country)
    except ValueError:
        problems.append(f"{rule_set.country!r} isn't a catalogued country")
    else:
        if rule_set.country != profile.code:
            problems.append(f"write the country code as {profile.code!r}")
        if rule_set.currency != profile.currency:
            problems.append(f"{profile.name} runs in {profile.currency}, not {rule_set.currency}")
    if not rule_set.tax_type or rule_set.tax_type != rule_set.tax_type.strip().lower():
        problems.append("tax_type must be a lower-case name such as 'vat'")
    if rule_set.effective_to is not None and rule_set.effective_to <= rule_set.effective_from:
        problems.append("effective_to must be later than effective_from")
    if rule_set.rounding.increment_minor < 1:
        problems.append("the rounding increment must be at least 1")
    problems += source_problems(rule_set.sources, rule_set.cited_sources())
    if not rule_set.components:
        problems.append("at least one component is required")
    codes = [component.code for component in rule_set.components]
    if len(codes) != len(set(codes)):
        problems.append("component codes must be unique within the rule set")
    for index, component in enumerate(rule_set.components):
        where = f"component {component.code}"
        if not (component.code.strip() and component.name.strip()):
            problems.append(f"{where}: a code and a name are required")
        if not 0 <= component.rate_ppm <= PPM:
            problems.append(f"{where}: rate_ppm must be between 0 and {PPM:,}")
        if not component.liability_account:
            problems.append(f"{where}: a liability account is required")
        if index == 0 and component.compound_on_previous:
            problems.append(f"{where}: the first component has nothing before it to compound on")
    return problems


def indirect_activation_problems(rule_set: IndirectTaxRuleSet) -> list[str]:
    return approval_problems(
        rule_set.status, rule_set.approval, rule_set.sources, rule_set.cited_sources()
    )


def require_active_indirect(rule_set: IndirectTaxRuleSet) -> None:
    problems = indirect_structural_problems(rule_set) + indirect_activation_problems(rule_set)
    if problems:
        raise RuleSetError(rule_set.id, problems)


@dataclass(frozen=True, slots=True)
class IndirectTaxLine:
    code: str
    name: str
    rate_ppm: int  # 0 for a zero-rated, exempt or out-of-scope supply
    base_minor: int
    amount_minor: int
    liability_account: str
    source: str


@dataclass(frozen=True, slots=True)
class IndirectTaxResult:
    rule_set_id: str
    country: str
    currency: str
    tax_type: str
    treatment: TaxTreatment
    inclusive: bool
    net_minor: int
    lines: tuple[IndirectTaxLine, ...]
    total_tax_minor: int
    total_minor: int
    effective_date: date


def calculate_indirect_tax(
    rule_set: IndirectTaxRuleSet,
    *,
    amount_minor: int,
    on: date,
    treatment: TaxTreatment = TaxTreatment.STANDARD,
    inclusive: bool = False,
) -> IndirectTaxResult:
    """Each component of the tax on one amount, rounded per the rule set.

    Tax-exclusive: amount_minor is the net amount and tax is added on top.
    Tax-inclusive: amount_minor is the gross amount and the tax is taken out
    of it; with more than one standard-rated component this is refused,
    because how the components share an inclusive price is a rule of each
    country that isn't modelled. Callers get rule sets from
    app.compliance.engine.registry, which refuses anything not approved.
    """
    problems = indirect_structural_problems(rule_set)
    if problems:
        raise RuleSetError(rule_set.id, problems)
    if amount_minor < 0:
        raise ValueError("amount_minor must not be negative; use a credit note")
    if not rule_set.applies_on(on):
        raise TaxConfigurationError(f"Rule set {rule_set.id} isn't in force on {on.isoformat()}.")

    def result(net: int, lines: tuple[IndirectTaxLine, ...], tax: int) -> IndirectTaxResult:
        return IndirectTaxResult(
            rule_set_id=rule_set.id,
            country=rule_set.country,
            currency=rule_set.currency,
            tax_type=rule_set.tax_type,
            treatment=treatment,
            inclusive=inclusive,
            net_minor=net,
            lines=lines,
            total_tax_minor=tax,
            total_minor=net + tax,
            effective_date=on,
        )

    def line(component: IndirectTaxComponent, rate: int, base: int, tax: int) -> IndirectTaxLine:
        return IndirectTaxLine(
            code=component.code,
            name=component.name,
            rate_ppm=rate,
            base_minor=base,
            amount_minor=tax,
            liability_account=component.liability_account,
            source=component.source,
        )

    if treatment is not TaxTreatment.STANDARD:
        return result(
            amount_minor,
            tuple(line(component, 0, amount_minor, 0) for component in rule_set.components),
            0,
        )

    if inclusive:
        if len(rule_set.components) > 1:
            raise TaxConfigurationError(
                f"Rule set {rule_set.id} has more than one component, and how they share a "
                "tax-inclusive price isn't modelled. Enter the amount before tax instead."
            )
        component = rule_set.components[0]
        tax = round_ratio(
            amount_minor * component.rate_ppm, PPM + component.rate_ppm, rule_set.rounding
        )
        net = amount_minor - tax
        return result(net, (line(component, component.rate_ppm, net, tax),), tax)

    lines: list[IndirectTaxLine] = []
    total_tax = 0
    for component in rule_set.components:
        base = amount_minor + total_tax if component.compound_on_previous else amount_minor
        tax = round_ratio(base * component.rate_ppm, PPM, rule_set.rounding)
        lines.append(line(component, component.rate_ppm, base, tax))
        total_tax += tax
    return result(amount_minor, tuple(lines), total_tax)
