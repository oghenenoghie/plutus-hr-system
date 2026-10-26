"""VAT and other transaction taxes on the engine. Every rate is fictional
(tests/unit/tax_engine_fixtures.py). The calculation cases come from the
single-rate calculator this replaces and from PR #62's tests."""

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.compliance.engine import registry
from app.compliance.engine.indirect_tax import (
    IndirectTaxComponent,
    IndirectTaxRuleSet,
    TaxTreatment,
    calculate_indirect_tax,
    indirect_activation_problems,
    indirect_structural_problems,
)
from app.compliance.engine.registry import (
    REGISTERED_INDIRECT_TAX_RULE_SETS,
    indirect_registry_problems,
    resolve_indirect_tax_rule_set,
)
from app.compliance.engine.rules import (
    Approval,
    Rounding,
    RoundingMode,
    RuleSetError,
    RuleSetStatus,
)
from app.compliance.multicountry import (
    CountryProfile,
    TaxConfigurationError,
    TaxStatus,
    get_country_profile,
)
from tests.unit.tax_engine_fixtures import APPROVED, HALF_UP, SOURCE

ON = date(2026, 4, 1)


def component(code: str = "VAT", rate_ppm: int = 160_000, **changes: Any) -> IndirectTaxComponent:
    return replace(
        IndirectTaxComponent(
            code=code,
            name=code,
            rate_ppm=rate_ppm,
            source="fixture",
            liability_account=f"{code.lower()}_payable",
        ),
        **changes,
    )


def vat(*components: IndirectTaxComponent, **changes: Any) -> IndirectTaxRuleSet:
    rule_set = IndirectTaxRuleSet(
        id="TEST-KE-VAT-1",
        country="KE",
        currency="KES",
        tax_type="vat",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        status=RuleSetStatus.ACTIVE,
        approval=APPROVED,
        sources=(SOURCE,),
        components=components or (component(),),
        rounding=HALF_UP,
    )
    return replace(rule_set, **changes)


def test_tax_exclusive_adds_each_component_on_the_net_amount() -> None:
    result = calculate_indirect_tax(vat(), amount_minor=10_000, on=ON)
    assert (result.net_minor, result.total_tax_minor, result.total_minor) == (10_000, 1_600, 11_600)
    assert (result.currency, result.rule_set_id, result.effective_date) == (
        "KES",
        "TEST-KE-VAT-1",
        ON,
    )
    (line,) = result.lines
    assert (line.code, line.rate_ppm, line.base_minor, line.amount_minor) == (
        "VAT",
        160_000,
        10_000,
        1_600,
    )
    assert line.liability_account == "vat_payable"


def test_tax_inclusive_takes_the_tax_out_of_the_price() -> None:
    rules = vat(component(rate_ppm=150_000))
    result = calculate_indirect_tax(rules, amount_minor=11_500, on=ON, inclusive=True)
    assert (result.net_minor, result.total_tax_minor, result.total_minor) == (10_000, 1_500, 11_500)


@pytest.mark.parametrize(
    ("inclusive", "amount", "expected_tax"),
    [
        # 5 * 10% = 0.5 -> 1, and 4 * 10% = 0.4 -> 0
        (False, 5, 1),
        (False, 4, 0),
        # 11 * 0.1 / 1.1 = 1 exactly; 6 -> 0.545... -> 1; 5 -> 0.4545... -> 0
        (True, 11, 1),
        (True, 6, 1),
        (True, 5, 0),
    ],
)
def test_rounding_is_half_up(inclusive: bool, amount: int, expected_tax: int) -> None:
    rules = vat(component(rate_ppm=100_000), id="TEST-RW-VAT-1", country="RW", currency="RWF")
    result = calculate_indirect_tax(rules, amount_minor=amount, on=ON, inclusive=inclusive)
    assert result.total_tax_minor == expected_tax


def test_a_currency_without_minor_units_can_round_to_a_coarser_increment() -> None:
    francs: dict[str, Any] = {"id": "TEST-CI-VAT-1", "country": "CI", "currency": "XOF"}
    exact = vat(component(rate_ppm=180_000), **francs)
    coarse = vat(component(rate_ppm=180_000), rounding=Rounding(RoundingMode.DOWN, 5), **francs)
    # 18% of 1,234 is 222.12
    assert calculate_indirect_tax(exact, amount_minor=1_234, on=ON).total_tax_minor == 222
    assert calculate_indirect_tax(coarse, amount_minor=1_234, on=ON).total_tax_minor == 220


def test_a_compounding_component_is_charged_on_the_net_plus_the_earlier_tax() -> None:
    rules = vat(
        component("A", 100_000),
        component("B", 100_000, compound_on_previous=True),
    )
    result = calculate_indirect_tax(rules, amount_minor=10_000, on=ON)
    assert [line.base_minor for line in result.lines] == [10_000, 11_000]
    assert [line.amount_minor for line in result.lines] == [1_000, 1_100]
    assert result.total_minor == 12_100


def test_separate_components_on_the_same_base_are_itemised() -> None:
    rules = vat(component("VAT", 150_000), component("LEVY", 50_000))
    result = calculate_indirect_tax(rules, amount_minor=10_000, on=ON)
    assert [(line.code, line.base_minor, line.amount_minor) for line in result.lines] == [
        ("VAT", 10_000, 1_500),
        ("LEVY", 10_000, 500),
    ]
    assert result.total_tax_minor == 2_000


@pytest.mark.parametrize(
    "treatment", [TaxTreatment.ZERO_RATED, TaxTreatment.EXEMPT, TaxTreatment.OUT_OF_SCOPE]
)
def test_a_supply_that_isnt_standard_rated_carries_no_tax_and_no_rate(
    treatment: TaxTreatment,
) -> None:
    rules = vat(component("VAT", 150_000), component("LEVY", 50_000))
    result = calculate_indirect_tax(rules, amount_minor=10_000, on=ON, treatment=treatment)
    assert (result.total_tax_minor, result.total_minor, result.treatment) == (0, 10_000, treatment)
    assert [(line.rate_ppm, line.amount_minor) for line in result.lines] == [(0, 0), (0, 0)]


def test_an_inclusive_price_with_several_components_is_refused() -> None:
    rules = vat(component("VAT", 150_000), component("LEVY", 50_000))
    with pytest.raises(TaxConfigurationError, match="more than one component"):
        calculate_indirect_tax(rules, amount_minor=12_000, on=ON, inclusive=True)


def test_the_rule_set_applies_from_its_start_up_to_but_not_on_its_end() -> None:
    rules = vat(effective_to=date(2026, 7, 1))
    assert calculate_indirect_tax(rules, amount_minor=100, on=date(2026, 6, 30)).total_minor
    for on in (date(2025, 12, 31), date(2026, 7, 1)):
        with pytest.raises(TaxConfigurationError, match="isn't in force"):
            calculate_indirect_tax(rules, amount_minor=100, on=on)


def test_a_negative_amount_is_refused() -> None:
    with pytest.raises(ValueError, match="credit note"):
        calculate_indirect_tax(vat(), amount_minor=-1, on=ON)


@pytest.mark.parametrize(
    ("rules", "problem"),
    [
        (vat(currency="USD"), "Kenya runs in KES, not USD"),
        (vat(country="ZZ"), "isn't a catalogued country"),
        (vat(tax_type="VAT"), "lower-case name"),
        (vat(effective_to=date(2026, 1, 1)), "effective_to must be later"),
        (vat(components=()), "at least one component"),
        (vat(component("VAT"), component("VAT")), "codes must be unique"),
        (vat(component(rate_ppm=1_000_001)), "rate_ppm must be between"),
        (vat(component(source="elsewhere")), "'elsewhere' is cited but not listed"),
        (vat(component(compound_on_previous=True)), "nothing before it to compound on"),
        (vat(component(liability_account="")), "a liability account is required"),
        (vat(rounding=Rounding(RoundingMode.DOWN, 0)), "rounding increment"),
    ],
)
def test_malformed_rule_sets_are_refused(rules: IndirectTaxRuleSet, problem: str) -> None:
    found = indirect_structural_problems(rules)
    assert any(problem in item for item in found), found
    with pytest.raises(RuleSetError, match="can't be used"):
        calculate_indirect_tax(rules, amount_minor=100, on=ON)


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"status": RuleSetStatus.DRAFT}, "status is draft, not active"),
        ({"approval": Approval(prepared_by="preparer@example.test")}, "no recorded approval"),
        ({"approval": replace(APPROVED, reviewed_by=None)}, "no tax adviser has reviewed it"),
        (
            {"approval": replace(APPROVED, approved_by=APPROVED.prepared_by)},
            "can't also approve it",
        ),
        ({"sources": (replace(SOURCE, official=False),)}, "isn't the law"),
    ],
)
def test_the_release_gate_is_the_same_as_for_payroll(changes: dict[str, Any], problem: str) -> None:
    assert any(problem in item for item in indirect_activation_problems(vat(**changes)))


def test_no_transaction_tax_rates_are_registered_yet_and_the_registry_is_consistent() -> None:
    assert indirect_registry_problems(REGISTERED_INDIRECT_TAX_RULE_SETS) == []


def test_registry_refuses_duplicates_and_overlapping_versions_of_the_same_tax() -> None:
    first = vat(effective_to=date(2026, 7, 1))
    overlapping = vat(id="TEST-KE-VAT-2", effective_from=date(2026, 6, 1))
    other_tax = vat(id="TEST-KE-WHT-1", tax_type="withholding_tax")
    problems = indirect_registry_problems([first, first, overlapping, other_tax])
    assert "rule set ids must be unique" in problems
    assert any("TEST-KE-VAT-2 are both in force" in problem for problem in problems)
    assert not any("TEST-KE-WHT-1" in problem for problem in problems)


def test_a_country_the_catalogue_doesnt_mark_active_is_refused_whatever_its_rates() -> None:
    with pytest.raises(TaxConfigurationError, match="not production-enabled"):
        resolve_indirect_tax_rule_set("KE", "vat", ON, rule_sets=[vat()])


@pytest.fixture
def kenya_marked_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """As if Kenya's catalogue entry had been moved to active."""

    def _active(country_code: str, *, tax_type: str) -> CountryProfile:
        return replace(get_country_profile(country_code), status=TaxStatus.ACTIVE)

    monkeypatch.setattr(registry, "require_configured_country", _active)


@pytest.mark.usefixtures("kenya_marked_active")
def test_the_rate_in_force_on_the_date_is_chosen() -> None:
    old = vat(id="TEST-KE-VAT-1", effective_to=date(2026, 9, 1))
    new = vat(component(rate_ppm=170_000), id="TEST-KE-VAT-2", effective_from=date(2026, 9, 1))
    both = [old, new]
    assert resolve_indirect_tax_rule_set("KE", "vat", date(2026, 8, 31), rule_sets=both) is old
    assert resolve_indirect_tax_rule_set("KE", "VAT", date(2026, 9, 1), rule_sets=both) is new
    with pytest.raises(TaxConfigurationError, match="No approved Kenya withholding_tax rates"):
        resolve_indirect_tax_rule_set("KE", "withholding_tax", ON, rule_sets=both)


@pytest.mark.usefixtures("kenya_marked_active")
def test_only_one_active_approved_rule_set_is_ever_resolved() -> None:
    with pytest.raises(TaxConfigurationError, match="No approved Kenya vat rates"):
        resolve_indirect_tax_rule_set("KE", "vat", ON, rule_sets=[vat(status=RuleSetStatus.DRAFT)])
    unapproved = vat(approval=Approval(prepared_by="preparer@example.test"))
    with pytest.raises(RuleSetError, match="no recorded approval"):
        resolve_indirect_tax_rule_set("KE", "vat", ON, rule_sets=[unapproved])
    with pytest.raises(TaxConfigurationError, match="More than one Kenya vat rule set"):
        resolve_indirect_tax_rule_set("KE", "vat", ON, rule_sets=[vat(), vat(id="TEST-KE-VAT-2")])


_AMOUNTS = st.integers(0, 10**12)
_RATES = st.integers(0, 1_000_000)


@given(amount=_AMOUNTS, rate=_RATES)
def test_inclusive_matches_the_calculator_it_replaces(amount: int, rate: int) -> None:
    """app.compliance.multicountry.calculate_percentage_tax extracted
    inclusive tax as (2 * gross * rate + d) // (2 * d), d = 1,000,000 + rate."""
    result = calculate_indirect_tax(
        vat(component(rate_ppm=rate)), amount_minor=amount, on=ON, inclusive=True
    )
    denominator = 1_000_000 + rate
    assert result.total_tax_minor == (2 * amount * rate + denominator) // (2 * denominator)
    assert result.net_minor + result.total_tax_minor == amount


@given(amount=_AMOUNTS, rates=st.lists(_RATES, min_size=1, max_size=4), compound=st.booleans())
def test_the_total_is_the_net_plus_every_component(
    amount: int, rates: list[int], compound: bool
) -> None:
    components = [
        component(f"C{index}", rate, compound_on_previous=compound and index > 0)
        for index, rate in enumerate(rates)
    ]
    result = calculate_indirect_tax(vat(*components), amount_minor=amount, on=ON)
    assert result.total_tax_minor == sum(line.amount_minor for line in result.lines)
    assert result.total_minor == result.net_minor + result.total_tax_minor


@given(gross=_AMOUNTS, rate=_RATES)
def test_taking_tax_out_then_adding_it_back_is_within_one_minor_unit(gross: int, rate: int) -> None:
    rules = vat(component(rate_ppm=rate))
    inclusive = calculate_indirect_tax(rules, amount_minor=gross, on=ON, inclusive=True)
    exclusive = calculate_indirect_tax(rules, amount_minor=inclusive.net_minor, on=ON)
    assert abs(exclusive.total_minor - gross) <= 1
