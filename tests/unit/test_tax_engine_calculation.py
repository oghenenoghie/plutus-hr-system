"""The engine's calculation, mechanism by mechanism. Every figure is
fictional (tests/unit/tax_engine_fixtures.py); the expected amounts are
worked out by hand in each test."""

import json
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.compliance.engine.calculate import (
    EmployeeFacts,
    LineKind,
    MissingEmployeeDataError,
    YearToDate,
    band_tax,
    calculate_payroll_levies,
    calculate_payslip,
)
from app.compliance.engine.postings import build_levy_postings, build_payslip_postings
from app.compliance.engine.rounding import rate_amount, round_ratio
from app.compliance.engine.rules import (
    AnnualFactRelief,
    Applicability,
    BandRounding,
    CountryRuleSet,
    DeductionCap,
    EarningCategory,
    EarningsBase,
    EmployeeFact,
    FamilySharesCredit,
    FixedCredit,
    NetPayBase,
    PayrollLevyRule,
    Rounding,
    RoundingMode,
    TaxBand,
    TaxMethod,
)
from app.compliance.multicountry import TaxConfigurationError
from app.domain.payroll.frequency import PayFrequency
from tests.unit.tax_engine_fixtures import (
    ALL_CASH,
    DUE,
    HALF_UP,
    basic,
    contribution,
    employer,
    pay,
    rule_set,
    tax_rule,
    units,
)


def test_progressive_tax_charges_each_band_only_on_its_slice() -> None:
    result = calculate_payslip(rule_set(), pay(basic(units(25_000))))
    # 10% of 10,000 + 30% of 15,000
    assert result.line("IT").amount_minor == units(1_000 + 4_500)
    assert result.net_pay_minor == units(25_000 - 5_500)
    assert result.gross_minor == units(25_000)


@pytest.mark.parametrize(
    ("gross", "tier_1", "tier_2", "tier_2_base"),
    [
        (3_000, 150, 0, 0),  # below the lower limit: tier 1 only
        (12_000, 250, 350, 7_000),  # between the limits
        (50_000, 250, 750, 15_000),  # above the upper limit: both capped
    ],
)
def test_tiered_contribution_between_lower_and_upper_earnings_limits(
    gross: int, tier_1: int, tier_2: int, tier_2_base: int
) -> None:
    rules = rule_set(
        contribution("T1", base_ceiling_minor=units(5_000)),
        contribution("T2", base_floor_minor=units(5_000), base_ceiling_minor=units(20_000)),
    )
    result = calculate_payslip(rules, pay(basic(units(gross))))
    assert result.line("T1").amount_minor == units(tier_1)
    assert result.line("T2").amount_minor == units(tier_2)
    assert result.line("T2").base_minor == units(tier_2_base)


@pytest.mark.parametrize(
    ("gross", "expected"),
    [
        (0, 0),  # nothing charged, so no minimum either
        (5_000, 150),  # 2% is 100: raised to the minimum
        (10_000, 200),
        (30_000, 400),  # 2% is 600: held to the cap
    ],
)
def test_contribution_minimum_and_cap(gross: int, expected: int) -> None:
    rules = rule_set(
        contribution(
            "HEALTH",
            rate_ppm=20_000,
            amount_floor_minor=units(150),
            amount_cap_minor=units(400),
        )
    )
    result = calculate_payslip(rules, pay(basic(units(gross))))
    assert result.line("HEALTH").amount_minor == units(expected)


def test_flat_per_head_employer_charge_is_a_cost_not_a_deduction() -> None:
    rules = rule_set(employer("LEVY", rate_ppm=None, flat_amount_minor=units(50)))
    result = calculate_payslip(rules, pay(basic(units(25_000))))
    line = result.line("LEVY")
    assert (line.kind, line.amount_minor, line.base_minor, line.rate_ppm) == (
        LineKind.EMPLOYER_CONTRIBUTION,
        units(50),
        0,
        None,
    )
    assert result.employer_contributions_minor == units(50)
    assert result.net_pay_minor == units(25_000 - 5_500)


def test_fixed_credit_comes_off_the_tax_and_never_below_zero() -> None:
    rules = rule_set(income_tax=tax_rule(credits=(FixedCredit("RELIEF", units(2_000), "fixture"),)))
    result = calculate_payslip(rules, pay(basic(units(25_000))))
    assert result.income_tax.tax_before_credits_minor == units(5_500)
    assert result.income_tax.credits_minor == units(2_000)
    assert result.line("IT").amount_minor == units(3_500)

    low = calculate_payslip(rules, pay(basic(units(5_000))))
    assert low.income_tax.tax_before_credits_minor == units(500)
    assert low.line("IT").amount_minor == 0


@pytest.mark.parametrize(("half_shares", "credit"), [(2, 0), (5, 1_500), (14, 4_000)])
def test_family_shares_credit_counts_half_shares_above_the_base_up_to_the_maximum(
    half_shares: int, credit: int
) -> None:
    shares = FamilySharesCredit("FAMILY", units(500), 2, 10, "fixture")
    rules = rule_set(income_tax=tax_rule(credits=(shares,)))
    result = calculate_payslip(
        rules, pay(basic(units(25_000)), facts=EmployeeFacts(half_shares=half_shares))
    )
    assert result.income_tax.credits_minor == units(credit)
    assert result.line("IT").amount_minor == units(5_500 - credit)


def test_family_shares_credit_refuses_an_employee_without_recorded_shares() -> None:
    shares = FamilySharesCredit("FAMILY", units(500), 2, 10, "fixture")
    rules = rule_set(income_tax=tax_rule(credits=(shares,)))
    with pytest.raises(MissingEmployeeDataError, match="family shares"):
        calculate_payslip(rules, pay(basic(units(25_000))))


@pytest.mark.parametrize(("cap", "expected_tax"), [(units(1_000), 5_200), (None, 4_750)])
def test_deductible_contributions_reduce_taxable_income_up_to_the_group_cap(
    cap: int | None, expected_tax: int
) -> None:
    rules = rule_set(
        contribution("PENSION", rate_ppm=100_000, tax_deduction_group="retirement"),
        income_tax=tax_rule(deduction_caps=(DeductionCap("retirement", cap),)),
    )
    result = calculate_payslip(rules, pay(basic(units(25_000))))
    assert result.line("PENSION").amount_minor == units(2_500)
    assert result.line("IT").amount_minor == units(expected_tax)
    assert result.net_pay_minor == units(25_000 - 2_500 - expected_tax)


def test_contribution_on_net_pay_is_worked_out_after_income_tax() -> None:
    rules = rule_set(contribution("NET", base=NetPayBase(), rate_ppm=5_000))
    result = calculate_payslip(rules, pay(basic(units(25_000))))
    codes = [line.code for line in result.lines]
    assert codes.index("NET") > codes.index("IT")
    assert result.line("NET").base_minor == units(19_500)
    assert result.line("NET").amount_minor == 9_750  # 0.5% of 19,500.00
    assert result.net_pay_minor == units(19_500) - 9_750


def test_contributions_for_expatriates_or_local_staff_only() -> None:
    rules = rule_set(
        employer("EXPAT", rate_ppm=100_000, applies_to=Applicability.EXPATRIATES),
        employer("LOCAL", rate_ppm=20_000, applies_to=Applicability.LOCAL_STAFF),
    )
    expat = calculate_payslip(
        rules, pay(basic(units(10_000)), facts=EmployeeFacts(is_expatriate=True))
    )
    local = calculate_payslip(
        rules, pay(basic(units(10_000)), facts=EmployeeFacts(is_expatriate=False))
    )
    assert [line.code for line in expat.lines] == ["EXPAT", "IT"]
    assert [line.code for line in local.lines] == ["LOCAL", "IT"]
    assert expat.line("EXPAT").amount_minor == units(1_000)
    assert local.line("LOCAL").amount_minor == units(200)
    with pytest.raises(MissingEmployeeDataError, match="expatriate"):
        calculate_payslip(rules, pay(basic(units(10_000))))


def test_currency_without_minor_units_rounds_to_the_franc_or_a_coarser_increment() -> None:
    francs = 123_456
    for mode, increment, expected in [
        (RoundingMode.HALF_UP, 1, 3_704),  # 3% is 3,703.68
        (RoundingMode.DOWN, 100, 3_700),
        (RoundingMode.UP, 100, 3_800),
        (RoundingMode.HALF_UP, 100, 3_700),
    ]:
        rounding = Rounding(mode, increment)
        rules = rule_set(
            contribution("PENSION", rate_ppm=30_000, rounding=rounding),
            id="RW-TEST-1",
            country="RW",
            currency="RWF",
            income_tax=tax_rule(bands=(TaxBand(None, 0),)),
        )
        result = calculate_payslip(rules, pay(basic(francs)))
        assert result.currency == "RWF"
        assert result.line("PENSION").amount_minor == expected


def test_rounding_to_an_increment_rounds_once_from_the_exact_amount() -> None:
    # 5% of 2,990 is 149.5. Rounding to 150 first and then to the nearest
    # 100 would give 200; rounded once from the exact amount it is 100.
    assert round_ratio(2_990 * 50_000, 1_000_000, Rounding(RoundingMode.HALF_UP, 100)) == 100


@given(base=st.integers(0, 10**12), rate=st.integers(0, 1_000_000))
def test_half_up_to_the_minor_unit_matches_the_existing_engine(base: int, rate: int) -> None:
    from app.domain.money import apply_rate_ppm

    assert rate_amount(base, rate, HALF_UP) == apply_rate_ppm(base, rate)


def test_band_rounding_each_band_or_once_on_the_total() -> None:
    bands = (TaxBand(5, 100_000), TaxBand(None, 100_000))
    each = tax_rule(bands=bands, band_rounding=BandRounding.EACH_BAND)
    total = tax_rule(bands=bands, band_rounding=BandRounding.TOTAL)
    # Two slices of 5 minor units at 10% are 0.5 each.
    assert band_tax(10, each) == 2
    assert band_tax(10, total) == 1


def _cumulative_rules() -> CountryRuleSet:
    relief = AnnualFactRelief(
        "RENT", EmployeeFact.ANNUAL_RENT_PAID, 200_000, units(6_000), HALF_UP, "fixture"
    )
    return rule_set(
        income_tax=tax_rule(
            method=TaxMethod.CUMULATIVE_ANNUAL,
            bands=(TaxBand(units(120_000), 0), TaxBand(None, 100_000)),
            reliefs=(relief,),
        ),
    )


def test_cumulative_method_taxes_the_year_to_date_and_spreads_relief_over_the_year() -> None:
    rules = _cumulative_rules()
    ytd = YearToDate()
    taxes = []
    for month in range(1, 13):
        result = calculate_payslip(
            rules,
            pay(
                basic(units(20_000)),
                facts=EmployeeFacts(annual_rent_paid_minor=units(60_000)),
                ytd=ytd,
                period_end=date(2026, month, 28),
                periods_elapsed=month,
            ),
        )
        # Relief: 20% of 60,000 is 12,000, capped at 6,000, recognised 1/12 a month.
        assert result.income_tax.reliefs_minor == units(6_000) * month // 12
        taxes.append(result.line("IT").amount_minor)
        ytd = result.year_to_date_after
    assert taxes[:6] == [0] * 6  # still within the 0% annual band
    # Over the year: 10% of (240,000 - 6,000 - 120,000)
    assert sum(taxes) == units(11_400)
    assert ytd.income_tax_withheld_minor == units(11_400)
    assert ytd.taxable_earnings_minor == units(240_000)


def test_pay_frequency_and_period_outside_the_rule_set_are_refused() -> None:
    with pytest.raises(TaxConfigurationError, match="weekly"):
        calculate_payslip(rule_set(), pay(basic(units(1_000)), frequency=PayFrequency.WEEKLY))
    with pytest.raises(TaxConfigurationError, match="isn't in force"):
        calculate_payslip(rule_set(), pay(basic(units(1_000)), period_end=date(2025, 12, 31)))


def test_negative_net_pay_is_refused() -> None:
    rules = rule_set(contribution("ALL", rate_ppm=900_000))
    with pytest.raises(ValueError, match="net pay is negative"):
        calculate_payslip(rules, pay(basic(units(25_000))))


def test_negative_earnings_are_refused() -> None:
    with pytest.raises(ValueError, match="basic earnings must not be negative"):
        calculate_payslip(rule_set(), pay(basic(-1)))


def test_payroll_levy_is_worked_out_once_on_the_run_total() -> None:
    levy = PayrollLevyRule(
        code="TRAINING",
        name="Training levy",
        authority="Training fund",
        base_categories=frozenset({EarningCategory.BASIC}),
        rate_ppm=10_000,
        rounding=HALF_UP,
        due=DUE,
        source="fixture",
        liability_account="training_levy_payable",
        expense_account="payroll_expense_training_levy",
    )
    rules = rule_set(payroll_levies=(levy,))
    employees = [pay(basic(50), (EarningCategory.VARIABLE, 1_000)).earnings] * 2
    (line,) = calculate_payroll_levies(
        rules,
        period_end=date(2026, 3, 31),
        frequency=PayFrequency.MONTHLY,
        earnings_by_employee=employees,
    )
    # 1% of each 50 would round to 1 apiece; 1% of the 100 total is 1.
    assert (line.base_minor, line.amount_minor, line.due_date) == (100, 1, date(2026, 4, 9))
    debit, credit = build_levy_postings([line])
    assert (debit.account, debit.debit_minor) == ("payroll_expense_training_levy", 1)
    assert (credit.account, credit.credit_minor) == ("training_levy_payable", 1)


def _everything() -> CountryRuleSet:
    return rule_set(
        contribution("T1", base_ceiling_minor=units(5_000), tax_deduction_group="pension"),
        contribution(
            "T2",
            base_floor_minor=units(5_000),
            base_ceiling_minor=units(20_000),
            tax_deduction_group="pension",
        ),
        employer("T1-ER", base_ceiling_minor=units(5_000), liability_account="t1_payable"),
        contribution(
            "HEALTH",
            rate_ppm=27_500,
            amount_floor_minor=units(300),
            base=EarningsBase(ALL_CASH),
        ),
        employer("LEVY", rate_ppm=None, flat_amount_minor=units(50)),
        contribution("NET", base=NetPayBase(), rate_ppm=5_000),
        income_tax=tax_rule(
            deduction_caps=(DeductionCap("pension", units(1_000)),),
            credits=(FixedCredit("RELIEF", units(2_000), "fixture"),),
        ),
    )


_AMOUNTS = st.integers(0, units(2_000_000))


# Basic pay of at least 1,000 so the 300 health minimum always fits in the
# pay; a minimum larger than the pay is refused (the test after this one).
@given(
    basic_pay=st.integers(units(1_000), units(2_000_000)),
    housing=_AMOUNTS,
    variable=_AMOUNTS,
)
def test_every_payslip_balances_and_nets_to_gross_less_deductions(
    basic_pay: int, housing: int, variable: int
) -> None:
    result = calculate_payslip(
        _everything(),
        pay(
            basic(basic_pay),
            (EarningCategory.HOUSING, housing),
            (EarningCategory.VARIABLE, variable),
        ),
    )
    assert result.net_pay_minor == result.gross_minor - result.employee_deductions_minor
    assert all(line.amount_minor >= 0 for line in result.lines)
    postings = build_payslip_postings(result)
    assert sum(p.debit_minor for p in postings) == sum(p.credit_minor for p in postings)
    assert sum(p.debit_minor for p in postings) == (
        result.gross_minor + result.employer_contributions_minor
    )


def test_a_minimum_contribution_larger_than_the_pay_is_refused_not_absorbed() -> None:
    rules = rule_set(contribution("HEALTH", rate_ppm=27_500, amount_floor_minor=units(300)))
    with pytest.raises(ValueError, match="net pay is negative"):
        calculate_payslip(rules, pay(basic(units(100))))


def test_snapshot_records_the_rule_set_inputs_and_every_line_as_json() -> None:
    result = calculate_payslip(_everything(), pay(basic(units(25_000))))
    snapshot = result.snapshot()
    json.dumps(snapshot)  # serialisable as it stands
    assert snapshot["rule_set_id"] == "KE-TEST-1"
    assert snapshot["currency"] == "KES"
    inputs = snapshot["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["period_end"] == "2026-03-31"
    lines = snapshot["lines"]
    assert isinstance(lines, list)
    assert [line["code"] for line in lines] == [line.code for line in result.lines]
