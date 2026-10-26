"""Rule-set validation, the release gate and the resolver. Every figure is
fictional (tests/unit/tax_engine_fixtures.py)."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from app.compliance.engine import registry
from app.compliance.engine.registry import (
    REGISTERED_RULE_SETS,
    registry_problems,
    resolve_rule_set,
)
from app.compliance.engine.rules import (
    AnnualFactRelief,
    Approval,
    CountryRuleSet,
    DeductionCap,
    DueDayOfFollowingMonth,
    EarningsBase,
    EmployeeFact,
    FixedCredit,
    NetPayBase,
    Rounding,
    RoundingMode,
    RuleSetError,
    RuleSetStatus,
    SourceReference,
    TaxBand,
    TaxMethod,
    activation_problems,
    require_active,
    structural_problems,
)
from app.compliance.multicountry import (
    CountryProfile,
    TaxConfigurationError,
    TaxStatus,
    get_country_profile,
)
from app.domain.payroll.frequency import PayFrequency
from tests.unit.tax_engine_fixtures import (
    APPROVED,
    HALF_UP,
    contribution,
    employer,
    rule_set,
    tax_rule,
    units,
)

ALL_FREQUENCIES = frozenset(PayFrequency)


def test_the_fixture_rule_set_is_well_formed_and_approved() -> None:
    rules = rule_set(contribution("PENSION"), employer("PENSION-ER"))
    assert structural_problems(rules) == []
    assert activation_problems(rules) == []
    require_active(rules)


_RELIEF = AnnualFactRelief("RENT", EmployeeFact.ANNUAL_RENT_PAID, 200_000, None, HALF_UP, "fixture")
_CUMULATIVE = tax_rule(method=TaxMethod.CUMULATIVE_ANNUAL, bands=(TaxBand(None, 100_000),))


@pytest.mark.parametrize(
    ("build", "problem"),
    [
        (lambda: rule_set(country="ZZ"), "isn't a catalogued country"),
        (lambda: rule_set(currency="USD"), "runs in KES, not USD"),
        (lambda: rule_set(effective_to=date(2026, 1, 1)), "effective_to must be later"),
        (lambda: rule_set(tax_year_start_month=13), "between 1 and 12"),
        (lambda: rule_set(frequencies=frozenset()), "at least one pay frequency"),
        (lambda: rule_set(frequencies=ALL_FREQUENCIES), "may list only one"),
        (lambda: rule_set(income_tax=tax_rule(source="nowhere")), "'nowhere' is cited"),
        (lambda: rule_set(contribution("IT")), "codes must be unique"),
        (lambda: rule_set(id="X" * 33), "longer than 32 characters"),
        (
            lambda: rule_set(contribution("PENSION", liability_account="p" * 65)),
            "longer than 64 characters",
        ),
        (lambda: rule_set(income_tax=tax_rule(authority="A" * 65)), "longer than 64 characters"),
        (lambda: rule_set(income_tax=tax_rule(bands=())), "at least one tax band"),
        (
            lambda: rule_set(income_tax=tax_rule(bands=(TaxBand(10, 0), TaxBand(5, 0)))),
            "must rise strictly",
        ),
        (
            lambda: rule_set(income_tax=tax_rule(bands=(TaxBand(None, 0), TaxBand(5, 0)))),
            "only the last band may be open-ended",
        ),
        (
            lambda: rule_set(income_tax=tax_rule(bands=(TaxBand(10, 0),))),
            "last band must be open-ended",
        ),
        (
            lambda: rule_set(income_tax=tax_rule(bands=(TaxBand(None, 1_000_001),))),
            "rate_ppm must be between",
        ),
        (
            lambda: rule_set(income_tax=tax_rule(rounding=Rounding(RoundingMode.DOWN, 0))),
            "rounding increment",
        ),
        (
            lambda: rule_set(income_tax=tax_rule(due=DueDayOfFollowingMonth(31))),
            "between 1 and 28",
        ),
        (
            lambda: rule_set(contribution("X", flat_amount_minor=units(10))),
            "exactly one of rate_ppm and flat_amount_minor",
        ),
        (
            lambda: rule_set(
                contribution("X", rate_ppm=None, flat_amount_minor=10, base_ceiling_minor=5)
            ),
            "takes no base or amount limits",
        ),
        (
            lambda: rule_set(contribution("X", base=EarningsBase(frozenset()))),
            "at least one category",
        ),
        (
            lambda: rule_set(contribution("X", base_floor_minor=10, base_ceiling_minor=10)),
            "ceiling must be above the base floor",
        ),
        (
            lambda: rule_set(contribution("X", amount_floor_minor=10, amount_cap_minor=5)),
            "floor must not exceed the amount cap",
        ),
        (
            lambda: rule_set(employer("X", expense_account=None)),
            "needs an expense account",
        ),
        (
            lambda: rule_set(contribution("X", expense_account="payroll_expense_x")),
            "has no expense account",
        ),
        (
            lambda: rule_set(contribution("X", tax_deduction_group="pension")),
            "has no DeductionCap",
        ),
        (
            lambda: rule_set(
                contribution("X", base=NetPayBase(), tax_deduction_group="g"),
                income_tax=tax_rule(deduction_caps=(DeductionCap("g", None),)),
            ),
            "on net pay can't be tax-deductible",
        ),
        (
            lambda: rule_set(
                employer("X", tax_deduction_group="g"),
                income_tax=tax_rule(deduction_caps=(DeductionCap("g", None),)),
            ),
            "only an employee contribution can be tax-deductible",
        ),
        (
            lambda: rule_set(
                income_tax=tax_rule(
                    credits=(FixedCredit("C", 150, "fixture"),),
                    rounding=Rounding(RoundingMode.HALF_UP, 100),
                )
            ),
            "whole rounding increment",
        ),
        (lambda: rule_set(income_tax=tax_rule(reliefs=(_RELIEF,))), "only supported on the cumul"),
        (
            lambda: rule_set(income_tax=_CUMULATIVE, effective_from=date(2026, 9, 1)),
            "take effect at a tax year's start",
        ),
        (
            lambda: rule_set(
                income_tax=replace(_CUMULATIVE, credits=(FixedCredit("C", 1, "fixture"),))
            ),
            "tax credits are only supported per period",
        ),
        (
            lambda: rule_set(
                income_tax=replace(_CUMULATIVE, deduction_caps=(DeductionCap("g", 5),))
            ),
            "deduction caps are only supported per period",
        ),
    ],
)
def test_malformed_rule_sets_are_refused_with_the_reason(
    build: Callable[[], CountryRuleSet], problem: str
) -> None:
    rules = build()
    assert any(problem in found for found in structural_problems(rules)), structural_problems(rules)
    with pytest.raises(RuleSetError, match="can't be used"):
        require_active(rules)


def test_a_cumulative_rule_set_with_rates_only_may_cover_every_pay_frequency() -> None:
    rules = rule_set(contribution("PENSION"), income_tax=_CUMULATIVE, frequencies=ALL_FREQUENCIES)
    assert structural_problems(rules) == []


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"status": RuleSetStatus.DRAFT}, "status is draft, not active"),
        ({"status": RuleSetStatus.APPROVED}, "status is approved, not active"),
        ({"approval": replace(APPROVED, reviewed_by=None)}, "no tax adviser has reviewed"),
        ({"approval": replace(APPROVED, approved_on=None)}, "no recorded approval"),
        (
            {"approval": replace(APPROVED, approved_by=APPROVED.prepared_by)},
            "can't also approve it",
        ),
        (
            {
                "sources": (
                    SourceReference(
                        "fixture",
                        "A payroll vendor's guide",
                        "https://example.test",
                        False,
                        date(2026, 10, 26),
                    ),
                )
            },
            "isn't the law or the authority's own publication",
        ),
    ],
)
def test_the_release_gate_refuses_anything_not_approved_from_official_sources(
    changes: dict[str, Any], problem: str
) -> None:
    rules = rule_set(**changes)
    assert structural_problems(rules) == []
    assert any(problem in found for found in activation_problems(rules))
    with pytest.raises(RuleSetError, match="can't be used"):
        require_active(rules)


def test_no_country_has_an_approved_rule_set_yet_and_the_registry_is_consistent() -> None:
    # Adding a country's rule set is a deliberate act behind the release
    # gate: whatever is registered must pass it.
    assert registry_problems(REGISTERED_RULE_SETS) == []
    for rules in REGISTERED_RULE_SETS:
        if rules.status is RuleSetStatus.ACTIVE:
            require_active(rules)


def test_registry_refuses_nigeria_duplicates_and_overlapping_versions() -> None:
    first = rule_set(effective_to=date(2026, 7, 1))
    overlapping = rule_set(id="TEST-KE-2", effective_from=date(2026, 6, 1))
    nigeria = rule_set(id="TEST-NG-1", country="NG", currency="NGN")
    problems = registry_problems([first, first, overlapping, nigeria])
    assert "rule set ids must be unique" in problems
    assert any("both in force at once" in problem for problem in problems)
    assert any("Nigeria still runs" in problem for problem in problems)


def test_a_country_the_catalogue_doesnt_mark_active_is_refused_whatever_its_rules() -> None:
    # Kenya is a draft in the catalogue, so even a fully approved rule set
    # can't be used for it.
    with pytest.raises(TaxConfigurationError, match="not production-enabled"):
        resolve_rule_set("KE", date(2026, 3, 31), rule_sets=[rule_set()])


@pytest.fixture
def kenya_marked_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """As if Kenya's catalogue entry had been moved to active."""

    def _active(country_code: str, *, tax_type: str) -> CountryProfile:
        return replace(get_country_profile(country_code), status=TaxStatus.ACTIVE)

    monkeypatch.setattr(registry, "require_configured_country", _active)


@pytest.mark.usefixtures("kenya_marked_active")
def test_a_mid_year_change_switches_rule_set_on_its_effective_date() -> None:
    january = rule_set(id="TEST-KE-1", effective_to=date(2026, 2, 1))
    february = rule_set(id="TEST-KE-2", effective_from=date(2026, 2, 1))
    both = [january, february]
    assert resolve_rule_set("KE", date(2026, 1, 31), rule_sets=both).id == "TEST-KE-1"
    assert resolve_rule_set("KE", date(2026, 2, 1), rule_sets=both).id == "TEST-KE-2"
    with pytest.raises(TaxConfigurationError, match="No approved Kenya payroll rules"):
        resolve_rule_set("KE", date(2025, 12, 31), rule_sets=both)


@pytest.mark.usefixtures("kenya_marked_active")
def test_only_an_active_approved_rule_set_is_ever_resolved() -> None:
    draft = rule_set(status=RuleSetStatus.DRAFT)
    with pytest.raises(TaxConfigurationError, match="No approved Kenya payroll rules"):
        resolve_rule_set("KE", date(2026, 3, 31), rule_sets=[draft])

    unapproved = rule_set(approval=Approval(prepared_by="preparer@example.test"))
    with pytest.raises(RuleSetError, match="no recorded approval"):
        resolve_rule_set("KE", date(2026, 3, 31), rule_sets=[unapproved])

    twice = [rule_set(), rule_set(id="TEST-KE-2")]
    with pytest.raises(TaxConfigurationError, match="More than one Kenya rule set"):
        resolve_rule_set("KE", date(2026, 3, 31), rule_sets=twice)
