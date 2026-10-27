"""The approved country rule sets, and the one gate a pay run or a
transaction gets its rules through.

REGISTERED_RULE_SETS holds The Gambia, Rwanda, Kenya, Ghana and Côte
d'Ivoire (app/compliance/engine/countries/), approved by Plutus Technologies
from published sources without a local tax adviser's review
(ApprovalBasis.OWNER_APPROVED). Each is a RuleSetTemplate: the figures its
sources didn't settle are entered by each organisation under Tax Settings,
and the rule set is built from them (app/compliance/engine/settings.py).
Whatever is registered must pass require_active once built.
Nigeria isn't registered: it runs on its RuleVersion path until it is moved
onto the engine behind its golden and pay-run regression tests.

REGISTERED_INDIRECT_TAX_RULE_SETS is empty: no country's VAT or other
transaction tax rates are approved, Nigeria's included.
"""

from collections.abc import Sequence
from datetime import date

from app.compliance.engine.countries import TEMPLATES
from app.compliance.engine.indirect_tax import (
    IndirectTaxRuleSet,
    indirect_structural_problems,
    require_active_indirect,
)
from app.compliance.engine.rules import (
    CountryRuleSet,
    RuleSetStatus,
    activation_problems,
    require_active,
    structural_problems,
)
from app.compliance.engine.settings import (
    RuleSetTemplate,
    SettingSpec,
    SettingValues,
    missing_settings,
    settings_problems,
)
from app.compliance.multicountry import TaxConfigurationError, require_configured_country

RegisteredRules = CountryRuleSet | RuleSetTemplate

REGISTERED_RULE_SETS: tuple[RegisteredRules, ...] = TEMPLATES
REGISTERED_INDIRECT_TAX_RULE_SETS: tuple[IndirectTaxRuleSet, ...] = ()


class MissingTaxSettingsError(TaxConfigurationError):
    """The organisation hasn't entered every figure its country's rules
    need for the period."""

    def __init__(self, country_name: str, missing: list[SettingSpec]) -> None:
        self.missing = missing
        labels = "; ".join(spec.label for spec in missing)
        super().__init__(
            f"{country_name}'s payroll needs {len(missing)} figure(s) your organisation enters "
            f"under Tax Settings before it can run: {labels}."
        )


def is_active(entry: RegisteredRules) -> bool:
    """Whether a registered entry may be resolved. A template is approved;
    what it lacks is each organisation's settings, not approval."""
    return isinstance(entry, RuleSetTemplate) or entry.status is RuleSetStatus.ACTIVE


_NIGERIA = "NG"


def _template_problems(template: RuleSetTemplate) -> list[str]:
    """A template's settings, and the rule set it builds with every setting
    at its first option: the same id, country and window, well formed and
    through the release gate."""
    problems = settings_problems(template)
    try:
        built = template.build(template.preview_values())
    except (KeyError, ValueError) as exc:
        return [*problems, f"{template.id}: doesn't build from its own settings: {exc}"]
    if (built.id, built.country, built.effective_from, built.effective_to) != (
        template.id,
        template.country,
        template.effective_from,
        template.effective_to,
    ):
        problems.append(f"{template.id}: builds a rule set with a different id, country or window")
    problems += [
        f"{template.id}: {problem}"
        for problem in structural_problems(built) + activation_problems(built)
    ]
    return problems


def registry_problems(rule_sets: Sequence[RegisteredRules]) -> list[str]:
    problems: list[str] = []
    ids = [rule_set.id for rule_set in rule_sets]
    if len(ids) != len(set(ids)):
        problems.append("rule set ids must be unique")
    for rule_set in rule_sets:
        if rule_set.country == _NIGERIA:
            problems.append(f"{rule_set.id}: Nigeria still runs on app.compliance.versions")
        if isinstance(rule_set, RuleSetTemplate):
            problems += _template_problems(rule_set)
        else:
            problems += [f"{rule_set.id}: {problem}" for problem in structural_problems(rule_set)]
    active = [rule_set for rule_set in rule_sets if is_active(rule_set)]
    for index, first in enumerate(active):
        for second in active[index + 1 :]:
            if first.country == second.country and _overlap(first, second):
                problems.append(f"{first.id} and {second.id} are both in force at once")
    return problems


def _overlap(
    first: RegisteredRules | IndirectTaxRuleSet, second: RegisteredRules | IndirectTaxRuleSet
) -> bool:
    first_ends_after_second_starts = (
        first.effective_to is None or second.effective_from < first.effective_to
    )
    second_ends_after_first_starts = (
        second.effective_to is None or first.effective_from < second.effective_to
    )
    return first_ends_after_second_starts and second_ends_after_first_starts


def rules_in_force(
    country_code: str,
    on: date,
    *,
    rule_sets: Sequence[RegisteredRules] | None = None,
) -> RegisteredRules:
    """The one approved rule set or template in force for the country on
    the date, before any settings are applied. Refuses (TaxConfigurationError)
    a country the catalogue doesn't mark active, a date no approved rule set
    covers, and two in force at once. Nothing falls back to another country
    or an earlier version."""
    profile = require_configured_country(country_code, tax_type="payroll")
    in_force = [
        rule_set
        for rule_set in (REGISTERED_RULE_SETS if rule_sets is None else rule_sets)
        if rule_set.country == profile.code and is_active(rule_set) and rule_set.applies_on(on)
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
    return in_force[0]


def registered_templates(country_code: str) -> list[RuleSetTemplate]:
    """Every registered template for the country, in effective order: the
    settings an organisation there may be asked for."""
    return sorted(
        (
            entry
            for entry in REGISTERED_RULE_SETS
            if isinstance(entry, RuleSetTemplate) and entry.country == country_code
        ),
        key=lambda template: template.effective_from,
    )


def resolve_rule_set(
    country_code: str,
    on: date,
    *,
    rule_sets: Sequence[RegisteredRules] | None = None,
    settings: SettingValues | None = None,
) -> CountryRuleSet:
    """The one approved rule set in force for the country on the date, from
    REGISTERED_RULE_SETS unless `rule_sets` is given, built from the
    organisation's `settings` where it is a template.

    Refuses what rules_in_force refuses, a template whose settings aren't
    all entered (MissingTaxSettingsError) or don't make a usable rule set,
    and a rule set that fails the release gate.
    """
    entry = rules_in_force(country_code, on, rule_sets=rule_sets)
    if isinstance(entry, CountryRuleSet):
        require_active(entry)
        return entry
    profile = require_configured_country(country_code, tax_type="payroll")
    values = dict(settings or {})
    missing = missing_settings(entry.settings, values)
    if missing:
        raise MissingTaxSettingsError(profile.name, missing)
    rule_set = entry.build(values)
    problems = structural_problems(rule_set)
    if problems:
        # The template is checked with its own options, so what's wrong here
        # comes from the organisation's values.
        raise TaxConfigurationError(
            f"{profile.name}'s Tax Settings don't make usable payroll rules: {'; '.join(problems)}."
        )
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
