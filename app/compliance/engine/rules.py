"""Country rule sets for the country-neutral payroll engine.

A CountryRuleSet holds one country's statutory payroll rules for one
effective-dated window: its employee and employer contributions, its income
tax, and its employer levies on the whole pay run, each citing the source it
came from. The calculation (app.compliance.engine.calculate) reads every rate,
limit and order from here; it has no country conditionals of its own.

No country's figures are encoded yet. A rule set is written only from figures
a local tax adviser has checked against the primary law (docs/countries/), and
the resolver (app.compliance.engine.registry) refuses any rule set that isn't
ACTIVE with a complete approval record. Nigeria still runs on its own
RuleVersion path (app.compliance.versions); the engine reproduces it exactly
(tests/golden/test_tax_engine_nigeria_parity.py) but isn't used for it.

Money is integer minor units of the rule set's currency, and rates are parts
per million (1,000,000 = 100%). Every per-period amount (a per-period band
edge, a ceiling, a flat charge, a credit, a deduction cap) is for one period of
the rule set's single pay frequency.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.compliance.multicountry import TaxConfigurationError, get_country_profile
from app.domain.payroll.frequency import PayFrequency

PPM = 1_000_000


class RuleSetError(TaxConfigurationError):
    """A rule set that is malformed, or isn't approved for the use asked of it."""

    def __init__(self, rule_set_id: str, problems: Sequence[str]) -> None:
        self.rule_set_id = rule_set_id
        self.problems = tuple(problems)
        super().__init__(f"Rule set {rule_set_id} can't be used: " + "; ".join(self.problems))


class RuleSetStatus(StrEnum):
    """The rule lifecycle in docs/architecture/multicountry-tax.md. Only
    ACTIVE is ever resolved for a pay run."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class EarningCategory(StrEnum):
    """What a cash earning is, so each contribution and tax can say which
    earnings its base is made of. Benefits in kind aren't modelled."""

    BASIC = "basic"
    HOUSING = "housing"
    TRANSPORT = "transport"
    FIXED_ALLOWANCE = "fixed_allowance"  # any other recurring allowance
    VARIABLE = "variable"  # overtime, bonus, commission and other irregular pay
    OTHER = "other"


class ContributionKind(StrEnum):
    EMPLOYEE = "employee"  # deducted from the employee's pay
    EMPLOYER = "employer"  # the employer's cost, never deducted from pay


class Applicability(StrEnum):
    """Which employees a contribution applies to. Anything but ALL needs the
    employee's expatriate status to be recorded."""

    ALL = "all"
    LOCAL_STAFF = "local_staff"
    EXPATRIATES = "expatriates"


class RoundingMode(StrEnum):
    HALF_UP = "half_up"
    DOWN = "down"
    UP = "up"


class TaxMethod(StrEnum):
    PER_PERIOD = "per_period"
    """Each period is taxed on its own, against the period table."""

    CUMULATIVE_ANNUAL = "cumulative_annual"
    """Tax on year-to-date taxable income against the annual table, less the
    tax already withheld this year."""


class BandRounding(StrEnum):
    EACH_BAND = "each_band"  # each band's slice of tax is rounded, then summed
    TOTAL = "total"  # the exact total is rounded once


class EmployeeFact(StrEnum):
    """Employee figures a relief can be based on (EmployeeFacts in calculate)."""

    ANNUAL_RENT_PAID = "annual_rent_paid_minor"


@dataclass(frozen=True, slots=True)
class Rounding:
    mode: RoundingMode
    increment_minor: int = 1  # e.g. 100 rounds to whole hundreds of the minor unit


@dataclass(frozen=True, slots=True)
class DueDayOfFollowingMonth:
    day: int  # 1 to 28, so it exists in every month


@dataclass(frozen=True, slots=True)
class DueDaysAfterPeriodEnd:
    days: int


@dataclass(frozen=True, slots=True)
class DueWorkingDaysAfterPeriodEnd:
    days: int  # weekends are skipped; public holidays aren't modelled


DueRule = DueDayOfFollowingMonth | DueDaysAfterPeriodEnd | DueWorkingDaysAfterPeriodEnd


@dataclass(frozen=True, slots=True)
class EarningsBase:
    """The sum of the period's earnings in these categories."""

    categories: frozenset[EarningCategory]


@dataclass(frozen=True, slots=True)
class NetPayBase:
    """Gross pay less income tax and every employee contribution on an
    earnings base. A contribution on this base is worked out after income
    tax, so it can't be deductible for income tax."""


ContributionBase = EarningsBase | NetPayBase


@dataclass(frozen=True, slots=True)
class SourceReference:
    id: str  # what rules cite, e.g. "nssf-notice-2026"
    title: str
    reference: str  # URL, gazette number, or section of the Act
    official: bool  # the law itself or the authority's own publication
    captured_on: date


@dataclass(frozen=True, slots=True)
class Approval:
    prepared_by: str
    reviewed_by: str | None = None  # the country's tax adviser
    approved_by: str | None = None
    approved_on: date | None = None


@dataclass(frozen=True, slots=True)
class ContributionRule:
    """One employee deduction or employer contribution, worked out per
    employee per period: a rate on a base between a floor and a ceiling, or a
    flat per-head amount."""

    code: str
    name: str
    kind: ContributionKind
    authority: str
    base: ContributionBase
    rounding: Rounding
    due: DueRule
    source: str
    liability_account: str
    expense_account: str | None = None  # required for an employer contribution
    rate_ppm: int | None = None
    flat_amount_minor: int | None = None  # a per-head charge, instead of a rate
    base_floor_minor: int = 0  # the base below this isn't charged (a lower earnings limit)
    base_ceiling_minor: int | None = None  # nor the base above this (an upper earnings limit)
    amount_floor_minor: int | None = None  # the least charged whenever any base is charged
    amount_cap_minor: int | None = None
    applies_to: Applicability = Applicability.ALL
    tax_deduction_group: str | None = None  # deductible before income tax, within the group's cap


@dataclass(frozen=True, slots=True)
class TaxBand:
    up_to_minor: int | None  # the band's cumulative ceiling; None for the open top band
    rate_ppm: int


@dataclass(frozen=True, slots=True)
class DeductionCap:
    """The most of a deduction group's contributions taken off taxable
    income in a period; None for no cap."""

    group: str
    cap_minor: int | None


@dataclass(frozen=True, slots=True)
class AnnualFactRelief:
    """A share of an annual employee figure, capped, taken off taxable
    income before banding and recognised pro rata through the tax year
    (rounded down), as cumulative tax recognises income."""

    code: str
    fact: EmployeeFact
    rate_ppm: int
    cap_minor: int | None
    rounding: Rounding
    source: str


@dataclass(frozen=True, slots=True)
class FixedCredit:
    """A fixed amount off the period's tax, never taking it below zero."""

    code: str
    amount_minor: int
    source: str


@dataclass(frozen=True, slots=True)
class FamilySharesCredit:
    """An amount off the period's tax for each half-share an employee has
    above base_half_shares, counting no more than max_half_shares."""

    code: str
    amount_per_half_share_minor: int
    base_half_shares: int
    max_half_shares: int
    source: str


TaxCredit = FixedCredit | FamilySharesCredit


@dataclass(frozen=True, slots=True)
class IncomeTaxRule:
    code: str
    name: str
    authority: str
    method: TaxMethod
    taxable_categories: frozenset[EarningCategory]
    bands: tuple[TaxBand, ...]  # per period (PER_PERIOD) or per year (CUMULATIVE_ANNUAL)
    band_rounding: BandRounding
    rounding: Rounding
    due: DueRule
    source: str
    liability_account: str
    deduction_caps: tuple[DeductionCap, ...] = ()
    reliefs: tuple[AnnualFactRelief, ...] = ()
    credits: tuple[TaxCredit, ...] = ()


@dataclass(frozen=True, slots=True)
class PayrollLevyRule:
    """An employer levy on the pay run's total of some earnings, worked out
    once per run rather than per employee."""

    code: str
    name: str
    authority: str
    base_categories: frozenset[EarningCategory]
    rate_ppm: int
    rounding: Rounding
    due: DueRule
    source: str
    liability_account: str
    expense_account: str


@dataclass(frozen=True, slots=True)
class CountryRuleSet:
    """A country's payroll rules in force from effective_from up to, but not
    including, effective_to: the same window RuleVersion uses."""

    id: str  # e.g. "KE-2026.1"
    country: str
    currency: str
    effective_from: date
    effective_to: date | None
    tax_year_start_month: int  # the tax year starts on the 1st of this month
    frequencies: frozenset[PayFrequency]
    status: RuleSetStatus
    approval: Approval
    sources: tuple[SourceReference, ...]
    income_tax: IncomeTaxRule
    contributions: tuple[ContributionRule, ...] = ()
    payroll_levies: tuple[PayrollLevyRule, ...] = ()

    def applies_on(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on < self.effective_to)

    def cited_sources(self) -> tuple[str, ...]:
        tax = self.income_tax
        return (
            tax.source,
            *(relief.source for relief in tax.reliefs),
            *(credit.source for credit in tax.credits),
            *(rule.source for rule in self.contributions),
            *(levy.source for levy in self.payroll_levies),
        )


def _rate_problem(where: str, rate_ppm: int) -> list[str]:
    if 0 <= rate_ppm <= PPM:
        return []
    return [f"{where}: rate_ppm must be between 0 and {PPM:,}"]


def _rounding_problems(where: str, rounding: Rounding) -> list[str]:
    if rounding.increment_minor >= 1:
        return []
    return [f"{where}: the rounding increment must be at least 1"]


def _due_problems(where: str, due: DueRule) -> list[str]:
    if isinstance(due, DueDayOfFollowingMonth):
        if not 1 <= due.day <= 28:
            return [f"{where}: the due day must be between 1 and 28"]
        return []
    if due.days < 0:
        return [f"{where}: due days must not be negative"]
    return []


def _band_problems(where: str, bands: tuple[TaxBand, ...]) -> list[str]:
    if not bands:
        return [f"{where}: at least one tax band is required"]
    problems: list[str] = []
    previous = 0
    for index, band in enumerate(bands):
        problems += _rate_problem(f"{where} band {index + 1}", band.rate_ppm)
        last = index == len(bands) - 1
        if band.up_to_minor is None:
            if not last:
                problems.append(f"{where}: only the last band may be open-ended")
            continue
        if band.up_to_minor <= previous:
            problems.append(f"{where}: band ceilings must rise strictly")
        previous = band.up_to_minor
    if bands[-1].up_to_minor is not None:
        problems.append(f"{where}: the last band must be open-ended")
    return problems


def _contribution_problems(rule: ContributionRule, groups: set[str]) -> list[str]:
    where = f"contribution {rule.code}"
    problems = _rounding_problems(where, rule.rounding) + _due_problems(where, rule.due)
    if (rule.rate_ppm is None) == (rule.flat_amount_minor is None):
        problems.append(f"{where}: give exactly one of rate_ppm and flat_amount_minor")
    if rule.rate_ppm is not None:
        problems += _rate_problem(where, rule.rate_ppm)
        if isinstance(rule.base, EarningsBase) and not rule.base.categories:
            problems.append(f"{where}: an earnings base needs at least one category")
    if rule.flat_amount_minor is not None:
        if rule.flat_amount_minor < 0:
            problems.append(f"{where}: the flat amount must not be negative")
        limits = (rule.base_ceiling_minor, rule.amount_floor_minor, rule.amount_cap_minor)
        if rule.base_floor_minor or any(limit is not None for limit in limits):
            problems.append(f"{where}: a flat amount takes no base or amount limits")
    if rule.base_floor_minor < 0:
        problems.append(f"{where}: the base floor must not be negative")
    if rule.base_ceiling_minor is not None and rule.base_ceiling_minor <= rule.base_floor_minor:
        problems.append(f"{where}: the base ceiling must be above the base floor")
    for value, label in ((rule.amount_floor_minor, "floor"), (rule.amount_cap_minor, "cap")):
        if value is not None and value < 0:
            problems.append(f"{where}: the amount {label} must not be negative")
    if (
        rule.amount_floor_minor is not None
        and rule.amount_cap_minor is not None
        and rule.amount_floor_minor > rule.amount_cap_minor
    ):
        problems.append(f"{where}: the amount floor must not exceed the amount cap")
    if rule.kind is ContributionKind.EMPLOYER and not rule.expense_account:
        problems.append(f"{where}: an employer contribution needs an expense account")
    if rule.kind is ContributionKind.EMPLOYEE and rule.expense_account is not None:
        problems.append(f"{where}: an employee contribution has no expense account")
    if not rule.liability_account:
        problems.append(f"{where}: a liability account is required")
    if rule.tax_deduction_group is not None:
        if rule.kind is not ContributionKind.EMPLOYEE:
            problems.append(f"{where}: only an employee contribution can be tax-deductible")
        if isinstance(rule.base, NetPayBase):
            problems.append(f"{where}: a contribution on net pay can't be tax-deductible")
        if rule.tax_deduction_group not in groups:
            problems.append(
                f"{where}: deduction group {rule.tax_deduction_group!r} has no DeductionCap"
            )
    return problems


def _income_tax_problems(rule_set: CountryRuleSet) -> list[str]:
    tax = rule_set.income_tax
    where = f"income tax {tax.code}"
    problems = _band_problems(where, tax.bands)
    problems += _rounding_problems(where, tax.rounding) + _due_problems(where, tax.due)
    if not tax.taxable_categories:
        problems.append(f"{where}: at least one taxable earnings category is required")
    if not tax.liability_account:
        problems.append(f"{where}: a liability account is required")
    groups = [cap.group for cap in tax.deduction_caps]
    if len(groups) != len(set(groups)):
        problems.append(f"{where}: each deduction group may be capped only once")
    for cap in tax.deduction_caps:
        if cap.cap_minor is not None and cap.cap_minor < 0:
            problems.append(f"{where}: the cap on group {cap.group!r} must not be negative")
    for relief in tax.reliefs:
        problems += _rate_problem(f"relief {relief.code}", relief.rate_ppm)
        problems += _rounding_problems(f"relief {relief.code}", relief.rounding)
        if relief.cap_minor is not None and relief.cap_minor < 0:
            problems.append(f"relief {relief.code}: the cap must not be negative")
    for credit in tax.credits:
        amount = (
            credit.amount_minor
            if isinstance(credit, FixedCredit)
            else credit.amount_per_half_share_minor
        )
        if amount < 0:
            problems.append(f"credit {credit.code}: the amount must not be negative")
        if amount % tax.rounding.increment_minor:
            problems.append(f"credit {credit.code}: the amount must be a whole rounding increment")
        if isinstance(credit, FamilySharesCredit) and not (
            0 <= credit.base_half_shares <= credit.max_half_shares
        ):
            problems.append(f"credit {credit.code}: need 0 <= base_half_shares <= max_half_shares")

    if tax.method is TaxMethod.CUMULATIVE_ANNUAL:
        # Year-to-date tax under one table only works if the table covers the
        # whole tax year; a mid-year change needs the adviser to say how
        # earlier periods are treated before it can be encoded.
        if (rule_set.effective_from.month, rule_set.effective_from.day) != (
            rule_set.tax_year_start_month,
            1,
        ):
            problems.append(f"{where}: a cumulative table must take effect at a tax year's start")
        if tax.credits:
            problems.append(f"{where}: tax credits are only supported per period")
        if any(cap.cap_minor is not None for cap in tax.deduction_caps):
            problems.append(f"{where}: deduction caps are only supported per period")
    elif tax.reliefs:
        problems.append(f"{where}: annual reliefs are only supported on the cumulative method")
    return problems


def _has_per_period_amounts(rule_set: CountryRuleSet) -> bool:
    tax = rule_set.income_tax
    if tax.method is TaxMethod.PER_PERIOD or tax.credits:
        return True
    if any(cap.cap_minor is not None for cap in tax.deduction_caps):
        return True
    return any(
        rule.flat_amount_minor is not None
        or rule.base_floor_minor
        or rule.base_ceiling_minor is not None
        or rule.amount_floor_minor is not None
        or rule.amount_cap_minor is not None
        for rule in rule_set.contributions
    )


def structural_problems(rule_set: CountryRuleSet) -> list[str]:
    """Everything that would make the rule set ambiguous or impossible to
    apply, whatever its status."""
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
    if rule_set.effective_to is not None and rule_set.effective_to <= rule_set.effective_from:
        problems.append("effective_to must be later than effective_from")
    if not 1 <= rule_set.tax_year_start_month <= 12:
        problems.append("tax_year_start_month must be between 1 and 12")
    if not rule_set.frequencies:
        problems.append("at least one pay frequency is required")
    elif len(rule_set.frequencies) > 1 and _has_per_period_amounts(rule_set):
        problems.append(
            "per-period amounts are for one pay frequency, so the rule set may list only one"
        )

    source_ids = [source.id for source in rule_set.sources]
    if len(source_ids) != len(set(source_ids)):
        problems.append("source ids must be unique")
    for source in rule_set.sources:
        if not (source.id.strip() and source.title.strip() and source.reference.strip()):
            problems.append("every source needs an id, a title and a reference")
    for cited in rule_set.cited_sources():
        if cited not in source_ids:
            problems.append(f"source {cited!r} is cited but not listed")

    tax = rule_set.income_tax
    codes = [
        tax.code,
        *(relief.code for relief in tax.reliefs),
        *(credit.code for credit in tax.credits),
        *(rule.code for rule in rule_set.contributions),
        *(levy.code for levy in rule_set.payroll_levies),
    ]
    if len(codes) != len(set(codes)):
        problems.append("rule codes must be unique within the rule set")

    problems += _income_tax_problems(rule_set)
    groups = {cap.group for cap in tax.deduction_caps}
    for rule in rule_set.contributions:
        problems += _contribution_problems(rule, groups)
    for levy in rule_set.payroll_levies:
        where = f"payroll levy {levy.code}"
        problems += _rate_problem(where, levy.rate_ppm)
        problems += _rounding_problems(where, levy.rounding) + _due_problems(where, levy.due)
        if not levy.base_categories:
            problems.append(f"{where}: at least one base category is required")
        if not (levy.liability_account and levy.expense_account):
            problems.append(f"{where}: an expense and a liability account are required")
    return problems


def activation_problems(rule_set: CountryRuleSet) -> list[str]:
    """What stops the rule set being used for real pay: the release gate in
    docs/architecture/multicountry-tax.md, as far as code can check it."""
    problems: list[str] = []
    if rule_set.status is not RuleSetStatus.ACTIVE:
        problems.append(f"its status is {rule_set.status.value}, not active")
    approval = rule_set.approval
    if not approval.reviewed_by:
        problems.append("no tax adviser has reviewed it")
    if not approval.approved_by or approval.approved_on is None:
        problems.append("it has no recorded approval")
    elif approval.approved_by == approval.prepared_by:
        problems.append("whoever prepared it can't also approve it")
    official = {source.id for source in rule_set.sources if source.official}
    for cited in sorted(set(rule_set.cited_sources())):
        if cited not in official:
            problems.append(f"source {cited!r} isn't the law or the authority's own publication")
    return problems


def require_well_formed(rule_set: CountryRuleSet) -> None:
    problems = structural_problems(rule_set)
    if problems:
        raise RuleSetError(rule_set.id, problems)


def require_active(rule_set: CountryRuleSet) -> None:
    problems = structural_problems(rule_set) + activation_problems(rule_set)
    if problems:
        raise RuleSetError(rule_set.id, problems)
