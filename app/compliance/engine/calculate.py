"""The country-neutral payroll calculation: one employee's statutory lines
for one period, and the employer's levies on a whole pay run, from a
CountryRuleSet. Pure functions with explicit inputs; no database, no clock,
no country conditionals.

The order is fixed: contributions on earnings, then income tax (after the
deductible contributions, reliefs and credits the rule set names), then
contributions on net pay. Non-statutory deductions (loans, benefits, union
dues) come off the net pay this returns, as they do for Nigeria today.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date
from enum import Enum, StrEnum

from app.compliance.engine.due_dates import due_date
from app.compliance.engine.rounding import rate_amount, round_ratio
from app.compliance.engine.rules import (
    PPM,
    AnnualFactRelief,
    Applicability,
    BandRounding,
    ContributionKind,
    ContributionRule,
    CountryRuleSet,
    EarningCategory,
    EmployeeFact,
    FixedCredit,
    IncomeTaxRule,
    NetPayBase,
    TaxCredit,
    TaxMethod,
    require_well_formed,
)
from app.compliance.multicountry import TaxConfigurationError
from app.domain.payroll.frequency import PayFrequency, periods_per_year


class MissingEmployeeDataError(ValueError):
    """A rule needs an employee figure that isn't recorded. The engine never
    assumes one."""


class LineKind(StrEnum):
    EMPLOYEE_CONTRIBUTION = "employee_contribution"
    EMPLOYER_CONTRIBUTION = "employer_contribution"
    INCOME_TAX = "income_tax"
    PAYROLL_LEVY = "payroll_levy"


@dataclass(frozen=True, slots=True)
class Earning:
    category: EarningCategory
    amount_minor: int


@dataclass(frozen=True, slots=True)
class EmployeeFacts:
    """Employee figures some rules depend on. None means not recorded, and a
    rule that needs it refuses to run."""

    annual_rent_paid_minor: int = 0
    half_shares: int | None = None  # family shares counted in halves (1 share = 2)
    is_expatriate: bool | None = None


@dataclass(frozen=True, slots=True)
class YearToDate:
    """The employee's totals for earlier periods of this tax year."""

    taxable_earnings_minor: int = 0
    tax_deductions_minor: int = 0
    income_tax_withheld_minor: int = 0


@dataclass(frozen=True, slots=True)
class PayslipInputs:
    period_end: date
    frequency: PayFrequency
    periods_elapsed_this_year: int  # including this period
    earnings: tuple[Earning, ...]
    facts: EmployeeFacts = field(default_factory=EmployeeFacts)
    year_to_date: YearToDate = field(default_factory=YearToDate)


@dataclass(frozen=True, slots=True)
class StatutoryLine:
    code: str
    name: str
    kind: LineKind
    authority: str
    base_minor: int  # the base actually charged; 0 for a flat or progressive amount
    rate_ppm: int | None
    amount_minor: int
    liability_account: str
    expense_account: str | None
    due_date: date
    source: str


@dataclass(frozen=True, slots=True)
class IncomeTaxWorking:
    """How the income tax was reached. Per period, these are the period's
    figures; on the cumulative method they are the year to date."""

    taxable_earnings_minor: int
    deductions_minor: int
    reliefs_minor: int
    taxable_income_minor: int
    tax_before_credits_minor: int
    credits_minor: int
    previously_withheld_minor: int
    tax_minor: int  # this period's tax


@dataclass(frozen=True, slots=True)
class PayslipResult:
    rule_set_id: str
    country: str
    currency: str
    inputs: PayslipInputs
    gross_minor: int
    lines: tuple[StatutoryLine, ...]
    income_tax: IncomeTaxWorking
    net_pay_minor: int
    year_to_date_after: YearToDate

    @property
    def employee_deductions_minor(self) -> int:
        """Everything statutory taken off the employee's pay."""
        return sum(
            line.amount_minor
            for line in self.lines
            if line.kind in (LineKind.EMPLOYEE_CONTRIBUTION, LineKind.INCOME_TAX)
        )

    @property
    def employer_contributions_minor(self) -> int:
        return sum(
            line.amount_minor for line in self.lines if line.kind is LineKind.EMPLOYER_CONTRIBUTION
        )

    def line(self, code: str) -> StatutoryLine:
        for line in self.lines:
            if line.code == code:
                return line
        raise KeyError(code)

    def snapshot(self) -> dict[str, object]:
        """Inputs, rule set and every figure, JSON-ready, so a posted
        payslip can be explained later without recalculating it."""
        return {item.name: _jsonable(getattr(self, item.name)) for item in fields(self)}


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, frozenset | set):
        return sorted(str(_jsonable(item)) for item in value)
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def _require_not_negative(values: Iterable[tuple[int, str]]) -> None:
    for value, name in values:
        if value < 0:
            raise ValueError(f"{name} must not be negative")


def _applies(rule: ContributionRule, facts: EmployeeFacts) -> bool:
    if rule.applies_to is Applicability.ALL:
        return True
    if facts.is_expatriate is None:
        raise MissingEmployeeDataError(
            f"{rule.name} depends on whether the employee is an expatriate, "
            "which isn't recorded for this employee."
        )
    return facts.is_expatriate is (rule.applies_to is Applicability.EXPATRIATES)


def _contribution_line(rule: ContributionRule, base_minor: int, period_end: date) -> StatutoryLine:
    if rule.flat_amount_minor is not None:
        charged, amount = 0, rule.flat_amount_minor
    elif rule.rate_ppm is None:  # require_well_formed: exactly one is set
        raise ValueError(f"{rule.code} has neither a rate nor a flat amount")
    else:
        upper = base_minor
        if rule.base_ceiling_minor is not None:
            upper = min(upper, rule.base_ceiling_minor)
        charged = max(0, upper - rule.base_floor_minor)
        amount = rate_amount(charged, rule.rate_ppm, rule.rounding)
        if charged > 0 and rule.amount_floor_minor is not None:
            amount = max(amount, rule.amount_floor_minor)
        if rule.amount_cap_minor is not None:
            amount = min(amount, rule.amount_cap_minor)
    employee = rule.kind is ContributionKind.EMPLOYEE
    return StatutoryLine(
        code=rule.code,
        name=rule.name,
        kind=LineKind.EMPLOYEE_CONTRIBUTION if employee else LineKind.EMPLOYER_CONTRIBUTION,
        authority=rule.authority,
        base_minor=charged,
        rate_ppm=rule.rate_ppm,
        amount_minor=amount,
        liability_account=rule.liability_account,
        expense_account=rule.expense_account,
        due_date=due_date(rule.due, period_end),
        source=rule.source,
    )


def band_tax(income_minor: int, rule: IncomeTaxRule) -> int:
    """Progressive tax: each band's rate applies only to the slice of income
    within it."""
    if income_minor < 0:
        raise ValueError("income_minor must not be negative")
    slices: list[tuple[int, int]] = []
    previous_ceiling = 0
    remaining = income_minor
    for band in rule.bands:
        if remaining <= 0:
            break
        width = remaining if band.up_to_minor is None else band.up_to_minor - previous_ceiling
        taxed = min(remaining, width)
        slices.append((taxed, band.rate_ppm))
        remaining -= taxed
        if band.up_to_minor is not None:
            previous_ceiling = band.up_to_minor
    if rule.band_rounding is BandRounding.EACH_BAND:
        return sum(rate_amount(taxed, rate, rule.rounding) for taxed, rate in slices)
    return round_ratio(sum(taxed * rate for taxed, rate in slices), PPM, rule.rounding)


def _relief_to_date(relief: AnnualFactRelief, inputs: PayslipInputs) -> int:
    if relief.fact is EmployeeFact.ANNUAL_RENT_PAID:
        figure = inputs.facts.annual_rent_paid_minor
    else:  # pragma: no cover - every EmployeeFact is handled above
        raise TypeError(f"unknown employee fact {relief.fact!r}")
    annual = rate_amount(figure, relief.rate_ppm, relief.rounding)
    if relief.cap_minor is not None:
        annual = min(annual, relief.cap_minor)
    total_periods = periods_per_year(inputs.frequency)
    return annual * min(inputs.periods_elapsed_this_year, total_periods) // total_periods


def _credit_amount(credit: TaxCredit, facts: EmployeeFacts) -> int:
    if isinstance(credit, FixedCredit):
        return credit.amount_minor
    if facts.half_shares is None:
        raise MissingEmployeeDataError(
            "This country's income tax depends on the employee's family shares "
            "(marital status and dependent children), which aren't recorded."
        )
    counted = min(facts.half_shares, credit.max_half_shares) - credit.base_half_shares
    return credit.amount_per_half_share_minor * max(0, counted)


def _capped_deductions(rule: IncomeTaxRule, deductible_by_group: dict[str, int]) -> int:
    caps = {cap.group: cap.cap_minor for cap in rule.deduction_caps}
    total = 0
    for group, amount in deductible_by_group.items():
        cap = caps[group]
        total += amount if cap is None else min(amount, cap)
    return total


def _income_tax(
    rule: IncomeTaxRule,
    period_earnings: int,
    period_deductions: int,
    inputs: PayslipInputs,
) -> tuple[StatutoryLine, IncomeTaxWorking]:
    ytd = inputs.year_to_date
    if rule.method is TaxMethod.CUMULATIVE_ANNUAL:
        earnings = ytd.taxable_earnings_minor + period_earnings
        deductions = ytd.tax_deductions_minor + period_deductions
        reliefs = sum(_relief_to_date(relief, inputs) for relief in rule.reliefs)
        previously_withheld = ytd.income_tax_withheld_minor
    else:
        earnings, deductions, reliefs, previously_withheld = (
            period_earnings,
            period_deductions,
            0,
            0,
        )
    taxable = max(0, earnings - deductions - reliefs)
    before_credits = band_tax(taxable, rule)
    credits = sum(_credit_amount(credit, inputs.facts) for credit in rule.credits)
    tax = max(0, before_credits - credits - previously_withheld)
    working = IncomeTaxWorking(
        taxable_earnings_minor=earnings,
        deductions_minor=deductions,
        reliefs_minor=reliefs,
        taxable_income_minor=taxable,
        tax_before_credits_minor=before_credits,
        credits_minor=credits,
        previously_withheld_minor=previously_withheld,
        tax_minor=tax,
    )
    line = StatutoryLine(
        code=rule.code,
        name=rule.name,
        kind=LineKind.INCOME_TAX,
        authority=rule.authority,
        base_minor=taxable,
        rate_ppm=None,
        amount_minor=tax,
        liability_account=rule.liability_account,
        expense_account=None,
        due_date=due_date(rule.due, inputs.period_end),
        source=rule.source,
    )
    return line, working


def require_usable_for(rule_set: CountryRuleSet, period_end: date, frequency: PayFrequency) -> None:
    require_well_formed(rule_set)
    if not rule_set.applies_on(period_end):
        raise TaxConfigurationError(
            f"Rule set {rule_set.id} isn't in force on {period_end.isoformat()}."
        )
    if frequency not in rule_set.frequencies:
        raise TaxConfigurationError(
            f"Rule set {rule_set.id} has no rules for {frequency.value} pay."
        )


def calculate_payslip(rule_set: CountryRuleSet, inputs: PayslipInputs) -> PayslipResult:
    """One employee's statutory lines and net pay for one period.

    Callers get rule sets from app.compliance.engine.registry, which refuses
    anything that isn't approved; this only checks the rule set is well
    formed and covers the period.
    """
    require_usable_for(rule_set, inputs.period_end, inputs.frequency)
    ytd = inputs.year_to_date
    _require_not_negative(
        [
            (earning.amount_minor, f"{earning.category.value} earnings")
            for earning in inputs.earnings
        ]
        + [
            (inputs.facts.annual_rent_paid_minor, "annual_rent_paid_minor"),
            (ytd.taxable_earnings_minor, "year-to-date taxable earnings"),
            (ytd.tax_deductions_minor, "year-to-date tax deductions"),
            (ytd.income_tax_withheld_minor, "year-to-date income tax withheld"),
        ]
    )
    if inputs.facts.half_shares is not None and inputs.facts.half_shares < 0:
        raise ValueError("half_shares must not be negative")
    if inputs.periods_elapsed_this_year < 1:
        raise ValueError("periods_elapsed_this_year counts this period, so it is at least 1")

    by_category: dict[EarningCategory, int] = defaultdict(int)
    for earning in inputs.earnings:
        by_category[earning.category] += earning.amount_minor
    gross = sum(by_category.values())

    lines: list[StatutoryLine] = []
    employee_on_earnings = 0
    deductible_by_group: dict[str, int] = defaultdict(int)
    on_net_pay: list[ContributionRule] = []
    for rule in rule_set.contributions:
        if not _applies(rule, inputs.facts):
            continue
        if isinstance(rule.base, NetPayBase):
            on_net_pay.append(rule)
            continue
        base = sum(by_category[category] for category in rule.base.categories)
        line = _contribution_line(rule, base, inputs.period_end)
        lines.append(line)
        if rule.kind is ContributionKind.EMPLOYEE:
            employee_on_earnings += line.amount_minor
            if rule.tax_deduction_group is not None:
                deductible_by_group[rule.tax_deduction_group] += line.amount_minor

    tax_rule = rule_set.income_tax
    period_earnings = sum(by_category[category] for category in tax_rule.taxable_categories)
    period_deductions = _capped_deductions(tax_rule, deductible_by_group)
    tax_line, working = _income_tax(tax_rule, period_earnings, period_deductions, inputs)
    lines.append(tax_line)

    net_pay = gross - employee_on_earnings - working.tax_minor
    _require_not_negative_net_pay(net_pay)
    net_pay_base = net_pay
    for rule in on_net_pay:
        line = _contribution_line(rule, net_pay_base, inputs.period_end)
        lines.append(line)
        if rule.kind is ContributionKind.EMPLOYEE:
            net_pay -= line.amount_minor
    _require_not_negative_net_pay(net_pay)

    return PayslipResult(
        rule_set_id=rule_set.id,
        country=rule_set.country,
        currency=rule_set.currency,
        inputs=inputs,
        gross_minor=gross,
        lines=tuple(lines),
        income_tax=working,
        net_pay_minor=net_pay,
        year_to_date_after=YearToDate(
            taxable_earnings_minor=ytd.taxable_earnings_minor + period_earnings,
            tax_deductions_minor=ytd.tax_deductions_minor + period_deductions,
            income_tax_withheld_minor=ytd.income_tax_withheld_minor + working.tax_minor,
        ),
    )


def _require_not_negative_net_pay(net_pay_minor: int) -> None:
    if net_pay_minor < 0:
        raise ValueError(
            "computed net pay is negative — check the earnings and the rule set's rates"
        )


def calculate_payroll_levies(
    rule_set: CountryRuleSet,
    *,
    period_end: date,
    frequency: PayFrequency,
    earnings_by_employee: Sequence[tuple[Earning, ...]],
) -> tuple[StatutoryLine, ...]:
    """The employer's levies on the pay run's total earnings, each worked
    out once on the total rather than per employee."""
    require_usable_for(rule_set, period_end, frequency)
    lines: list[StatutoryLine] = []
    for levy in rule_set.payroll_levies:
        base = 0
        for earnings in earnings_by_employee:
            for earning in earnings:
                if earning.amount_minor < 0:
                    raise ValueError(f"{earning.category.value} earnings must not be negative")
                if earning.category in levy.base_categories:
                    base += earning.amount_minor
        lines.append(
            StatutoryLine(
                code=levy.code,
                name=levy.name,
                kind=LineKind.PAYROLL_LEVY,
                authority=levy.authority,
                base_minor=base,
                rate_ppm=levy.rate_ppm,
                amount_minor=rate_amount(base, levy.rate_ppm, levy.rounding),
                liability_account=levy.liability_account,
                expense_account=levy.expense_account,
                due_date=due_date(levy.due, period_end),
                source=levy.source,
            )
        )
    return tuple(lines)
