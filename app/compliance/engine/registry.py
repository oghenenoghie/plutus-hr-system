"""The approved country rule sets, and the one gate a pay run or a
transaction gets its rules through.

REGISTERED_RULE_SETS is empty: no country beyond Nigeria has rules a local
tax adviser has approved (docs/countries/README.md). A country's rule set is
added here only once it passes require_active, which checks the approval
record and that every rule cites the law or the authority's own publication.
Nigeria isn't registered: it runs on its RuleVersion path until it is moved
onto the engine behind its golden and pay-run regression tests.

REGISTERED_INDIRECT_TAX_RULE_SETS is empty too: no country's VAT or other
transaction tax rates are approved, Nigeria's included.
"""

from collections.abc import Sequence
from datetime import date

from app.compliance.engine.indirect_tax import (
    IndirectTaxRuleSet,
    indirect_structural_problems,
    require_active_indirect,
)
from app.compliance.engine.rules import (
    CountryRuleSet,
    RuleSetStatus,
    require_active,
    structural_problems,
)
from app.compliance.multicountry import TaxConfigurationError, require_configured_country

REGISTERED_RULE_SETS: tuple[CountryRuleSet, ...] = ()
REGISTERED_INDIRECT_TAX_RULE_SETS: tuple[IndirectTaxRuleSet, ...] = ()

_NIGERIA = "NG"


def registry_problems(rule_sets: Sequence[CountryRuleSet]) -> list[str]:
    problems: list[str] = []
    ids = [rule_set.id for rule_set in rule_sets]
    if len(ids) != len(set(ids)):
        problems.append("rule set ids must be unique")
    for rule_set in rule_sets:
        if rule_set.country == _NIGERIA:
            problems.append(f"{rule_set.id}: Nigeria still runs on app.compliance.versions")
        problems += [f"{rule_set.id}: {problem}" for problem in structural_problems(rule_set)]
    active = [rule_set for rule_set in rule_sets if rule_set.status is RuleSetStatus.ACTIVE]
    for index, first in enumerate(active):
        for second in active[index + 1 :]:
            if first.country == second.country and _overlap(first, second):
                problems.append(f"{first.id} and {second.id} are both in force at once")
    return problems


def _overlap(
    first: CountryRuleSet | IndirectTaxRuleSet, second: CountryRuleSet | IndirectTaxRuleSet
) -> bool:
    first_ends_after_second_starts = (
        first.effective_to is None or second.effective_from < first.effective_to
    )
    second_ends_after_first_starts = (
        second.effective_to is None or first.effective_from < second.effective_to
    )
    return first_ends_after_second_starts and second_ends_after_first_starts


def resolve_rule_set(
    country_code: str,
    on: date,
    *,
    rule_sets: Sequence[CountryRuleSet] | None = None,
) -> CountryRuleSet:
    """The one approved rule set in force for the country on the date, from
    REGISTERED_RULE_SETS unless `rule_sets` is given.

    Refuses (TaxConfigurationError) a country the catalogue doesn't mark
    active, a date no active rule set covers, two rule sets in force at once,
    and a rule set that fails the release gate. Nothing falls back to another
    country or an earlier version.
    """
    profile = require_configured_country(country_code, tax_type="payroll")
    in_force = [
        rule_set
        for rule_set in (REGISTERED_RULE_SETS if rule_sets is None else rule_sets)
        if rule_set.country == profile.code
        and rule_set.status is RuleSetStatus.ACTIVE
        and rule_set.applies_on(on)
    ]
    if not in_force:
        raise TaxConfigurationError(
            f"No approved {profile.name} payroll rules are in force on {on.isoformat()}."
        )
    if len(in_force) > 1:
        ids = ", ".join(rule_set.id for rule_set in in_force)
        raise TaxConfigurationError(
            f"More than one {profile.name} rule set is in force on {on.isoformat()}: {ids}."
        )
    rule_set = in_force[0]
    require_active(rule_set)
    return rule_set


def indirect_registry_problems(rule_sets: Sequence[IndirectTaxRuleSet]) -> list[str]:
    problems: list[str] = []
    ids = [rule_set.id for rule_set in rule_sets]
    if len(ids) != len(set(ids)):
        problems.append("rule set ids must be unique")
    for rule_set in rule_sets:
        problems += [
            f"{rule_set.id}: {problem}" for problem in indirect_structural_problems(rule_set)
        ]
    active = [rule_set for rule_set in rule_sets if rule_set.status is RuleSetStatus.ACTIVE]
    for index, first in enumerate(active):
        for second in active[index + 1 :]:
            same_tax = (first.country, first.tax_type) == (second.country, second.tax_type)
            if same_tax and _overlap(first, second):
                problems.append(f"{first.id} and {second.id} are both in force at once")
    return problems


def resolve_indirect_tax_rule_set(
    country_code: str,
    tax_type: str,
    on: date,
    *,
    rule_sets: Sequence[IndirectTaxRuleSet] | None = None,
) -> IndirectTaxRuleSet:
    """The one approved rule set in force for the country's tax on the date,
    from REGISTERED_INDIRECT_TAX_RULE_SETS unless `rule_sets` is given,
    refusing exactly what resolve_rule_set refuses."""
    profile = require_configured_country(country_code, tax_type=tax_type)
    wanted = tax_type.strip().lower()
    in_force = [
        rule_set
        for rule_set in (REGISTERED_INDIRECT_TAX_RULE_SETS if rule_sets is None else rule_sets)
        if rule_set.country == profile.code
        and rule_set.tax_type == wanted
        and rule_set.status is RuleSetStatus.ACTIVE
        and rule_set.applies_on(on)
    ]
    if not in_force:
        raise TaxConfigurationError(
            f"No approved {profile.name} {wanted} rates are in force on {on.isoformat()}."
        )
    if len(in_force) > 1:
        ids = ", ".join(rule_set.id for rule_set in in_force)
        raise TaxConfigurationError(
            f"More than one {profile.name} {wanted} rule set is in force on "
            f"{on.isoformat()}: {ids}."
        )
    rule_set = in_force[0]
    require_active_indirect(rule_set)
    return rule_set
