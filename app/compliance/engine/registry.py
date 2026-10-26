"""The approved country rule sets, and the one gate a pay run gets its rules
through.

REGISTERED_RULE_SETS is empty: no country beyond Nigeria has rules a local
tax adviser has approved (docs/countries/README.md). A country's rule set is
added here only once it passes require_active, which checks the approval
record and that every rule cites the law or the authority's own publication.
Nigeria isn't registered: it runs on its RuleVersion path until it is moved
onto the engine behind its golden and pay-run regression tests.
"""

from collections.abc import Sequence
from datetime import date

from app.compliance.engine.rules import (
    CountryRuleSet,
    RuleSetStatus,
    require_active,
    structural_problems,
)
from app.compliance.multicountry import TaxConfigurationError, require_configured_country

REGISTERED_RULE_SETS: tuple[CountryRuleSet, ...] = ()

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


def _overlap(first: CountryRuleSet, second: CountryRuleSet) -> bool:
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
    rule_sets: Sequence[CountryRuleSet] = REGISTERED_RULE_SETS,
) -> CountryRuleSet:
    """The one approved rule set in force for the country on the date.

    Refuses (TaxConfigurationError) a country the catalogue doesn't mark
    active, a date no active rule set covers, two rule sets in force at once,
    and a rule set that fails the release gate. Nothing falls back to another
    country or an earlier version.
    """
    profile = require_configured_country(country_code, tax_type="payroll")
    in_force = [
        rule_set
        for rule_set in rule_sets
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
