"""Builders for engine tests. Every figure these produce is fictional: they
exercise the engine's arithmetic and rules, and none is a real rate,
threshold or deadline for any country."""

from dataclasses import replace
from datetime import date
from typing import Any

from app.compliance.engine.calculate import Earning, EmployeeFacts, PayslipInputs, YearToDate
from app.compliance.engine.rules import (
    Approval,
    BandRounding,
    ContributionKind,
    ContributionRule,
    CountryRuleSet,
    DueDayOfFollowingMonth,
    EarningCategory,
    EarningsBase,
    IncomeTaxRule,
    Rounding,
    RoundingMode,
    RuleSetStatus,
    SourceReference,
    TaxBand,
    TaxMethod,
)
from app.domain.payroll.frequency import PayFrequency

ALL_CASH = frozenset(EarningCategory)
HALF_UP = Rounding(RoundingMode.HALF_UP)
DUE = DueDayOfFollowingMonth(9)
SOURCE = SourceReference(
    id="fixture",
    title="Engine test fixture (fictional figures)",
    reference="tests/unit/tax_engine_fixtures.py",
    official=True,
    captured_on=date(2026, 10, 26),
)
APPROVED = Approval(
    prepared_by="preparer@example.test",
    reviewed_by="adviser@example.test",
    approved_by="approver@example.test",
    approved_on=date(2026, 10, 1),
)


def units(whole: int) -> int:
    """A whole amount in minor units of a two-decimal currency."""
    return whole * 100


def tax_rule(**changes: Any) -> IncomeTaxRule:
    """10% on the first 10,000 a month, 30% above."""
    rule = IncomeTaxRule(
        code="IT",
        name="Income tax",
        authority="Revenue authority",
        method=TaxMethod.PER_PERIOD,
        taxable_categories=ALL_CASH,
        bands=(TaxBand(units(10_000), 100_000), TaxBand(None, 300_000)),
        band_rounding=BandRounding.EACH_BAND,
        rounding=HALF_UP,
        due=DUE,
        source="fixture",
        liability_account="income_tax_payable",
    )
    return replace(rule, **changes)


def contribution(code: str, **changes: Any) -> ContributionRule:
    """An employee contribution of 5% of all cash earnings, unless changed."""
    rule = ContributionRule(
        code=code,
        name=code,
        kind=ContributionKind.EMPLOYEE,
        authority="Fund",
        base=EarningsBase(ALL_CASH),
        rounding=HALF_UP,
        due=DUE,
        source="fixture",
        liability_account=f"{code.lower()}_payable",
        rate_ppm=50_000,
    )
    return replace(rule, **changes)


def employer(code: str, **changes: Any) -> ContributionRule:
    defaults: dict[str, Any] = {
        "kind": ContributionKind.EMPLOYER,
        "expense_account": f"payroll_expense_{code.lower()}",
    }
    return contribution(code, **(defaults | changes))


def rule_set(
    *contributions: ContributionRule,
    income_tax: IncomeTaxRule | None = None,
    **changes: Any,
) -> CountryRuleSet:
    rules = CountryRuleSet(
        id="KE-TEST-1",
        country="KE",
        currency="KES",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        tax_year_start_month=1,
        frequencies=frozenset({PayFrequency.MONTHLY}),
        status=RuleSetStatus.ACTIVE,
        approval=APPROVED,
        sources=(SOURCE,),
        income_tax=income_tax or tax_rule(),
        contributions=contributions,
    )
    return replace(rules, **changes)


def pay(
    *earnings: tuple[EarningCategory, int],
    facts: EmployeeFacts | None = None,
    ytd: YearToDate | None = None,
    period_end: date = date(2026, 3, 31),
    frequency: PayFrequency = PayFrequency.MONTHLY,
    periods_elapsed: int = 3,
) -> PayslipInputs:
    return PayslipInputs(
        period_end=period_end,
        frequency=frequency,
        periods_elapsed_this_year=periods_elapsed,
        earnings=tuple(Earning(category, amount) for category, amount in earnings),
        facts=facts or EmployeeFacts(),
        year_to_date=ytd or YearToDate(),
    )


def basic(amount_minor: int) -> tuple[EarningCategory, int]:
    return (EarningCategory.BASIC, amount_minor)
