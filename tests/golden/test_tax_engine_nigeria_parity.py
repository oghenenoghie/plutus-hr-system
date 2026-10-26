"""The country-neutral engine reproduces Nigeria's payroll exactly.

nigeria_rule_set() restates NG-2026.1 in the engine's terms, reading every
figure from the RuleVersion itself, so nothing here can drift from Nigeria's
rules. The engine's PAYE, pension, NHF, net pay, postings, NSITF and due dates
must then equal the existing Nigerian functions' to the kobo: on the
hand-verified golden case and on generated pay histories. Nigeria's payroll
keeps running on app.domain.payroll; this is the evidence a later switch-over
needs, not the switch-over.
"""

from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from app.compliance.engine.calculate import (
    Earning,
    EmployeeFacts,
    PayslipInputs,
    YearToDate,
    calculate_payroll_levies,
    calculate_payslip,
)
from app.compliance.engine.postings import build_levy_postings, build_payslip_postings
from app.compliance.engine.rules import (
    AnnualFactRelief,
    Approval,
    BandRounding,
    ContributionKind,
    ContributionRule,
    CountryRuleSet,
    DeductionCap,
    DueDayOfFollowingMonth,
    DueDaysAfterPeriodEnd,
    DueWorkingDaysAfterPeriodEnd,
    EarningCategory,
    EarningsBase,
    EmployeeFact,
    IncomeTaxRule,
    PayrollLevyRule,
    Rounding,
    RoundingMode,
    RuleSetStatus,
    SourceReference,
    TaxBand,
    TaxMethod,
    structural_problems,
)
from app.compliance.models import RuleVersion
from app.compliance.versions.ng_2026_1 import NG_2026_1
from app.domain.payroll.deadlines import (
    nhf_deadline,
    nsitf_deadline,
    paye_deadline,
    pension_deadline,
)
from app.domain.payroll.frequency import PayFrequency, periods_per_year
from app.domain.payroll.nsitf import compute_nsitf
from app.domain.payroll.payslip import PayslipComputation, compute_payslip
from app.domain.payroll.postings import Posting
from app.domain.payroll.postings import build_payslip_postings as nigerian_postings

HALF_UP = Rounding(RoundingMode.HALF_UP)
PENSIONABLE = frozenset({EarningCategory.BASIC, EarningCategory.HOUSING, EarningCategory.TRANSPORT})
STATUTORY = "statutory"  # pension (employee) and NHF come off taxable income uncapped


def nigeria_rule_set(version: RuleVersion) -> CountryRuleSet:
    source = SourceReference(
        id="ng-reference",
        title=f"{version.id} (app/compliance/versions/ng_2026_1.py)",
        reference=".claude/skills/plutus-payroll-python/references/nigeria-statutory-compliance.md",
        official=False,
        captured_on=date(2026, 10, 26),
    )
    paye, pension, nhf, nsitf = version.paye, version.pension, version.nhf, version.nsitf

    pension_due = DueWorkingDaysAfterPeriodEnd(pension.due_working_days_after_payment)
    pension_employee = ContributionRule(
        code="PENSION",
        name="Pension (employee)",
        kind=ContributionKind.EMPLOYEE,
        authority=pension.authority,
        base=EarningsBase(PENSIONABLE),
        rounding=HALF_UP,
        due=pension_due,
        source=source.id,
        liability_account="pension_payable",
        rate_ppm=pension.employee_rate_ppm,
        tax_deduction_group=STATUTORY,
    )
    pension_employer = ContributionRule(
        code="PENSION-ER",
        name="Pension (employer)",
        kind=ContributionKind.EMPLOYER,
        authority=pension.authority,
        base=EarningsBase(PENSIONABLE),
        rounding=HALF_UP,
        due=pension_due,
        source=source.id,
        liability_account="pension_payable",
        expense_account="payroll_expense_employer_pension",
        rate_ppm=pension.employer_rate_ppm,
    )
    nhf_employee = ContributionRule(
        code="NHF",
        name="NHF",
        kind=ContributionKind.EMPLOYEE,
        authority=nhf.authority,
        base=EarningsBase(frozenset({EarningCategory.BASIC})),
        rounding=HALF_UP,
        due=DueDaysAfterPeriodEnd(nhf.due_days_after_payment),
        source=source.id,
        liability_account="nhf_payable",
        rate_ppm=nhf.rate_ppm,
        tax_deduction_group=STATUTORY,
    )

    return CountryRuleSet(
        id=f"{version.id}-engine",
        country=version.country,
        currency="NGN",
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        tax_year_start_month=1,
        frequencies=frozenset(PayFrequency),
        # The calculation needs only a well-formed rule set; the release gate
        # is for registering a country, and Nigeria isn't registered.
        status=RuleSetStatus.IN_REVIEW,
        approval=Approval(prepared_by="tests/golden"),
        sources=(source,),
        income_tax=IncomeTaxRule(
            code="PAYE",
            name="PAYE",
            authority=paye.authority,
            method=TaxMethod.CUMULATIVE_ANNUAL,
            taxable_categories=frozenset(EarningCategory),
            bands=tuple(TaxBand(band.up_to_minor, band.rate_ppm) for band in paye.bands),
            band_rounding=BandRounding.EACH_BAND,
            rounding=HALF_UP,
            due=DueDayOfFollowingMonth(paye.due_day_of_following_month),
            source=source.id,
            liability_account="paye_payable",
            deduction_caps=(DeductionCap(STATUTORY, None),),
            reliefs=(
                AnnualFactRelief(
                    code="RENT",
                    fact=EmployeeFact.ANNUAL_RENT_PAID,
                    rate_ppm=paye.rent_relief_rate_ppm,
                    cap_minor=paye.rent_relief_cap_minor,
                    rounding=HALF_UP,
                    source=source.id,
                ),
            ),
        ),
        contributions=(pension_employee, pension_employer, nhf_employee),
        payroll_levies=(
            PayrollLevyRule(
                code="NSITF",
                name="NSITF",
                authority=nsitf.authority,
                base_categories=PENSIONABLE,
                rate_ppm=nsitf.rate_ppm,
                rounding=HALF_UP,
                due=DueDayOfFollowingMonth(nsitf.due_day_of_following_month),
                source=source.id,
                liability_account="nsitf_payable",
                expense_account="payroll_expense_nsitf",
            ),
        ),
    )


NIGERIA = nigeria_rule_set(NG_2026_1)


def kobo(naira: int) -> int:
    return naira * 100


def _earnings(basic: int, housing: int, transport: int, other: int) -> tuple[Earning, ...]:
    return (
        Earning(EarningCategory.BASIC, basic),
        Earning(EarningCategory.HOUSING, housing),
        Earning(EarningCategory.TRANSPORT, transport),
        Earning(EarningCategory.OTHER, other),
    )


def _by_account(postings: tuple[Posting, ...]) -> dict[str, tuple[int, int]]:
    """Debit and credit per account. Nigeria's postings keep a zero gross
    line when there is no pay; the engine leaves every zero line out."""
    totals: dict[str, tuple[int, int]] = {}
    for posting in postings:
        debit, credit = totals.get(posting.account, (0, 0))
        totals[posting.account] = (debit + posting.debit_minor, credit + posting.credit_minor)
    return {account: amounts for account, amounts in totals.items() if amounts != (0, 0)}


def _assert_same(engine_inputs: PayslipInputs, nigerian: PayslipComputation) -> YearToDate:
    result = calculate_payslip(NIGERIA, engine_inputs)
    assert result.gross_minor == nigerian.gross_minor
    assert result.line("PENSION").amount_minor == nigerian.pension_employee_minor
    assert result.line("PENSION-ER").amount_minor == nigerian.pension_employer_minor
    assert result.line("NHF").amount_minor == nigerian.nhf_minor
    assert result.line("PAYE").amount_minor == nigerian.paye_minor
    assert result.income_tax.reliefs_minor == nigerian.cumulative_rent_relief_minor
    assert result.income_tax.taxable_income_minor == nigerian.cumulative_chargeable_income_minor
    assert result.net_pay_minor == nigerian.net_pay_minor

    assert _by_account(build_payslip_postings(result)) == _by_account(nigerian_postings(nigerian))

    period_end = engine_inputs.period_end
    assert result.line("PAYE").due_date == paye_deadline(period_end, NG_2026_1.paye)
    assert result.line("PENSION").due_date == pension_deadline(period_end, NG_2026_1.pension)
    assert result.line("NHF").due_date == nhf_deadline(period_end, NG_2026_1.nhf)
    return result.year_to_date_after


def test_engine_reproduces_the_hand_verified_three_month_payslip() -> None:
    """tests/golden/test_payslip.py's case: PAYE ₦0, ₦5,750, ₦62,875."""
    ytd = YearToDate()
    nigerian_ytd = (0, 0, 0, 0)  # gross, pension (employee), NHF, PAYE
    expected_paye = [0, kobo(5_750), kobo(62_875)]
    for month, paye in enumerate(expected_paye, start=1):
        earnings = (kobo(300_000), kobo(150_000), kobo(50_000), 0)
        nigerian = compute_payslip(
            basic_minor=earnings[0],
            housing_minor=earnings[1],
            transport_minor=earnings[2],
            other_earnings_minor=earnings[3],
            annual_rent_paid_minor=kobo(2_000_000),
            periods_elapsed_this_year=month,
            frequency=PayFrequency.MONTHLY,
            cumulative_gross_before_minor=nigerian_ytd[0],
            cumulative_pension_employee_before_minor=nigerian_ytd[1],
            cumulative_nhf_before_minor=nigerian_ytd[2],
            cumulative_paye_withheld_before_minor=nigerian_ytd[3],
            rules=NG_2026_1,
        )
        assert nigerian.paye_minor == paye
        ytd = _assert_same(
            PayslipInputs(
                period_end=date(2026, month, 28),
                frequency=PayFrequency.MONTHLY,
                periods_elapsed_this_year=month,
                earnings=_earnings(*earnings),
                facts=EmployeeFacts(annual_rent_paid_minor=kobo(2_000_000)),
                year_to_date=ytd,
            ),
            nigerian,
        )
        nigerian_ytd = (
            nigerian_ytd[0] + nigerian.gross_minor,
            nigerian_ytd[1] + nigerian.pension_employee_minor,
            nigerian_ytd[2] + nigerian.nhf_minor,
            nigerian_ytd[3] + nigerian.paye_minor,
        )
    assert ytd.income_tax_withheld_minor == kobo(5_750 + 62_875)


_PAY = st.tuples(
    st.integers(0, kobo(20_000_000)),  # basic
    st.integers(0, kobo(10_000_000)),  # housing
    st.integers(0, kobo(5_000_000)),  # transport
    st.integers(0, kobo(10_000_000)),  # other earnings
)


@settings(max_examples=300, deadline=None)
@given(
    frequency=st.sampled_from(list(PayFrequency)),
    rent=st.integers(0, kobo(20_000_000)),
    history=st.lists(_PAY, min_size=1, max_size=14),
    first_period_end=st.dates(date(2026, 1, 1), date(2026, 12, 31)),
)
def test_engine_matches_nigerian_payroll_on_generated_pay_histories(
    frequency: PayFrequency,
    rent: int,
    history: list[tuple[int, int, int, int]],
    first_period_end: date,
) -> None:
    ytd = YearToDate()
    nigerian_ytd = (0, 0, 0, 0)
    for period, (basic, housing, transport, other) in enumerate(
        history[: periods_per_year(frequency)], start=1
    ):
        nigerian = compute_payslip(
            basic_minor=basic,
            housing_minor=housing,
            transport_minor=transport,
            other_earnings_minor=other,
            annual_rent_paid_minor=rent,
            periods_elapsed_this_year=period,
            frequency=frequency,
            cumulative_gross_before_minor=nigerian_ytd[0],
            cumulative_pension_employee_before_minor=nigerian_ytd[1],
            cumulative_nhf_before_minor=nigerian_ytd[2],
            cumulative_paye_withheld_before_minor=nigerian_ytd[3],
            rules=NG_2026_1,
        )
        ytd = _assert_same(
            PayslipInputs(
                period_end=first_period_end,
                frequency=frequency,
                periods_elapsed_this_year=period,
                earnings=_earnings(basic, housing, transport, other),
                facts=EmployeeFacts(annual_rent_paid_minor=rent),
                year_to_date=ytd,
            ),
            nigerian,
        )
        nigerian_ytd = (
            nigerian_ytd[0] + nigerian.gross_minor,
            nigerian_ytd[1] + nigerian.pension_employee_minor,
            nigerian_ytd[2] + nigerian.nhf_minor,
            nigerian_ytd[3] + nigerian.paye_minor,
        )


@given(employees=st.lists(_PAY, min_size=0, max_size=30))
def test_engine_nsitf_matches_the_pay_run_liability(
    employees: list[tuple[int, int, int, int]],
) -> None:
    """statutory_liability.py charges NSITF once on the run's total
    pensionable pay (basic + housing + transport)."""
    period_end = date(2026, 3, 31)
    (line,) = calculate_payroll_levies(
        NIGERIA,
        period_end=period_end,
        frequency=PayFrequency.MONTHLY,
        earnings_by_employee=[_earnings(*pay) for pay in employees],
    )
    pensionable = sum(basic + housing + transport for basic, housing, transport, _ in employees)
    assert line.base_minor == pensionable
    assert line.amount_minor == compute_nsitf(pensionable, NG_2026_1.nsitf)
    assert line.due_date == nsitf_deadline(period_end, NG_2026_1.nsitf)
    if line.amount_minor:
        debit, credit = build_levy_postings([line])
        assert (debit.account, credit.account) == ("payroll_expense_nsitf", "nsitf_payable")


def test_the_restated_nigerian_rules_are_well_formed() -> None:
    assert structural_problems(NIGERIA) == []
