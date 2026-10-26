"""Pay runs for an organisation whose country is on the country-neutral
engine (app.compliance.engine), and the statutory lines, liabilities, levies
and ledger accounts they produce. Nigeria keeps its own path
(app.domain.payroll); app.services.payroll chooses between them.

Nothing here runs for a real organisation until a country's rule set is
approved and registered (app.compliance.engine.registry): resolve_rule_set
refuses every country before that.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.engine.calculate import (
    Earning,
    EmployeeFacts,
    LineKind,
    MissingEmployeeDataError,
    PayslipInputs,
    PayslipResult,
    StatutoryLine,
    YearToDate,
    calculate_payroll_levies,
    calculate_payslip,
    require_usable_for,
)
from app.compliance.engine.postings import build_levy_postings
from app.compliance.engine.registry import resolve_rule_set
from app.compliance.engine.rules import CountryRuleSet, EarningCategory
from app.domain.accounting.posting_rules import PostingLine
from app.domain.payroll.frequency import PayFrequency
from app.models.employee import Employee
from app.models.journal_entry import JournalSourceType
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip
from app.models.payslip_statutory_line import PayslipStatutoryLine
from app.models.statutory_liability import LiabilityScheme, StatutoryLiability
from app.services.chart_accounts import seed_rule_set_accounts
from app.services.posting import post_journal

# Keys this module writes into Payslip.derivation.
ENGINE_SNAPSHOT_KEY = "engine"
ENGINE_PERIOD_KEY = "engine_period"


def rule_set_for(country_code: str, period_end: date) -> CountryRuleSet:
    """The approved rule set for the pay period, or TaxConfigurationError."""
    return resolve_rule_set(country_code, period_end)


def require_rules_for_run(
    country_code: str, *, period_end: date, frequency: PayFrequency
) -> CountryRuleSet:
    """The rule set a run of this period and frequency will calculate with,
    so validating a run refuses (TaxConfigurationError) what locking it
    would."""
    rule_set = rule_set_for(country_code, period_end)
    require_usable_for(rule_set, period_end, frequency)
    return rule_set


def tax_year_start(period_end: date, start_month: int) -> date:
    year = period_end.year if period_end.month >= start_month else period_end.year - 1
    return date(year, start_month, 1)


def year_to_date_before(
    db: Session, employee_id: uuid.UUID, year_start: date
) -> tuple[YearToDate, int]:
    """The employee's engine totals for earlier periods of this tax year, and
    how many periods there were. Only payslips of LOCKED runs count, so a
    reversed run never feeds the year to date (as cumulative_totals_before
    does for Nigeria)."""
    prior = db.scalars(
        select(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(Payslip.employee_id == employee_id)
        .where(Payslip.period_end >= year_start)
        .where(PayRun.status == PayRunStatus.LOCKED)
    ).all()
    taxable = deductions = withheld = 0
    for payslip in prior:
        period = payslip.derivation.get(ENGINE_PERIOD_KEY)
        if not isinstance(period, dict):
            continue
        taxable += int(period["taxable_earnings_minor"])
        deductions += int(period["tax_deductions_minor"])
        withheld += int(period["income_tax_minor"])
    return YearToDate(taxable, deductions, withheld), len(prior)


def earnings_for(
    *,
    basic_minor: int,
    housing_minor: int,
    transport_minor: int,
    recurring_other_minor: int,
    overtime_minor: int,
    one_off_minor: int,
) -> tuple[Earning, ...]:
    """The period's earnings by category. The employee's recurring "other
    earnings" are fixed allowances; overtime is variable pay; leave payouts,
    gratuity and other one-off amounts are other earnings. Each country's
    rule set says which categories each of its bases includes."""
    return (
        Earning(EarningCategory.BASIC, basic_minor),
        Earning(EarningCategory.HOUSING, housing_minor),
        Earning(EarningCategory.TRANSPORT, transport_minor),
        Earning(EarningCategory.FIXED_ALLOWANCE, recurring_other_minor),
        Earning(EarningCategory.VARIABLE, overtime_minor),
        Earning(EarningCategory.OTHER, one_off_minor),
    )


def facts_for(employee: Employee) -> EmployeeFacts:
    return EmployeeFacts(
        annual_rent_paid_minor=employee.annual_rent_paid_minor,
        half_shares=employee.tax_half_shares,
        is_expatriate=employee.is_expatriate,
    )


def compute(
    rule_set: CountryRuleSet,
    *,
    employee: Employee,
    period_end: date,
    earnings: tuple[Earning, ...],
    year_to_date: YearToDate,
    periods_elapsed_this_year: int,
) -> PayslipResult:
    """The employee's payslip on the rule set. A rule that needs a figure
    the employee's record lacks refuses (MissingEmployeeDataError), naming
    the employee so the record can be completed."""
    try:
        return calculate_payslip(
            rule_set,
            PayslipInputs(
                period_end=period_end,
                frequency=employee.pay_frequency,
                periods_elapsed_this_year=periods_elapsed_this_year,
                earnings=earnings,
                facts=facts_for(employee),
                year_to_date=year_to_date,
            ),
        )
    except MissingEmployeeDataError as exc:
        raise MissingEmployeeDataError(f"Employee {employee.employee_number}: {exc}") from exc


def simulate_engine_payslip(
    db: Session, *, employee: Employee, country: str, period_end: date
) -> PayslipResult:
    """The period's statutory figures at the employee's stored pay, with no
    proration, overtime or one-offs and nothing persisted: what the
    variance check before locking compares against, as Nigeria's
    simulate_payslip does."""
    rule_set = rule_set_for(country, period_end)
    year_start = tax_year_start(period_end, rule_set.tax_year_start_month)
    year_to_date, periods_before = year_to_date_before(db, employee.id, year_start)
    return compute(
        rule_set,
        employee=employee,
        period_end=period_end,
        earnings=earnings_for(
            basic_minor=employee.basic_minor,
            housing_minor=employee.housing_minor,
            transport_minor=employee.transport_minor,
            recurring_other_minor=employee.other_earnings_minor,
            overtime_minor=0,
            one_off_minor=0,
        ),
        year_to_date=year_to_date,
        periods_elapsed_this_year=periods_before + 1,
    )


def period_figures(result: PayslipResult) -> dict[str, int]:
    """This period's own contribution to the year to date, stored on the
    payslip so later periods can sum them."""
    before, after = result.inputs.year_to_date, result.year_to_date_after
    return {
        "taxable_earnings_minor": after.taxable_earnings_minor - before.taxable_earnings_minor,
        "tax_deductions_minor": after.tax_deductions_minor - before.tax_deductions_minor,
        "income_tax_minor": after.income_tax_withheld_minor - before.income_tax_withheld_minor,
    }


def income_tax_minor(result: PayslipResult) -> int:
    return sum(line.amount_minor for line in result.lines if line.kind is LineKind.INCOME_TAX)


def record_lines(
    db: Session, *, org_id: uuid.UUID, payslip: Payslip, result: PayslipResult
) -> list[PayslipStatutoryLine]:
    rows = [
        PayslipStatutoryLine(
            org_id=org_id,
            payslip_id=payslip.id,
            pay_run_id=payslip.pay_run_id,
            rule_set_id=result.rule_set_id,
            position=position,
            code=line.code,
            name=line.name,
            kind=line.kind.value,
            authority=line.authority,
            base_minor=line.base_minor,
            rate_ppm=line.rate_ppm,
            amount_minor=line.amount_minor,
            liability_account=line.liability_account,
            expense_account=line.expense_account,
            due_date=line.due_date,
            source=line.source,
        )
        for position, line in enumerate(result.lines)
    ]
    db.add_all(rows)
    return rows


@dataclass(frozen=True)
class _LiabilityKey:
    liability_account: str
    authority: str
    due_date: date


def _country_liability(
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    key: _LiabilityKey,
    codes: Sequence[str],
    base_minor: int,
    amount_minor: int,
) -> StatutoryLiability:
    return StatutoryLiability(
        org_id=org_id,
        pay_run_id=pay_run.id,
        scheme=LiabilityScheme.COUNTRY,
        line_code="+".join(sorted(set(codes))),
        liability_account=key.liability_account,
        authority=key.authority,
        base_minor=base_minor,
        amount_minor=amount_minor,
        period_start=pay_run.period_start,
        period_end=pay_run.period_end,
        due_date=key.due_date,
    )


def generate_liabilities(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    payslips: Sequence[Payslip],
    rule_set: CountryRuleSet,
) -> list[StatutoryLiability]:
    """One liability per payable account, authority and due date across the
    run's payslips (an employee's and the employer's share of the same
    contribution are paid together), plus the run's payroll levies, which
    are also posted here: they have no per-employee posting."""
    lines = db.scalars(
        select(PayslipStatutoryLine).where(
            PayslipStatutoryLine.payslip_id.in_([payslip.id for payslip in payslips])
        )
    ).all()
    codes: dict[_LiabilityKey, list[str]] = defaultdict(list)
    amounts: dict[_LiabilityKey, int] = defaultdict(int)
    # The earnings a liability was worked out on count once per payslip: an
    # employee's and the employer's share of a contribution are on the same
    # pay, as Nigeria's pension liability counts pensionable pay once.
    bases: dict[_LiabilityKey, dict[uuid.UUID, int]] = defaultdict(dict)
    for line in lines:
        key = _LiabilityKey(line.liability_account, line.authority, line.due_date)
        codes[key].append(line.code)
        amounts[key] += line.amount_minor
        payslip_bases = bases[key]
        payslip_bases[line.payslip_id] = max(payslip_bases.get(line.payslip_id, 0), line.base_minor)

    liabilities = [
        _country_liability(
            org_id=org_id,
            pay_run=pay_run,
            key=key,
            codes=codes[key],
            base_minor=sum(bases[key].values()),
            amount_minor=amounts[key],
        )
        for key in codes
        if amounts[key] > 0
    ]

    levy_lines = calculate_payroll_levies(
        rule_set,
        period_end=pay_run.period_end,
        frequency=pay_run.frequency,
        earnings_by_employee=[earnings_of(payslip) for payslip in payslips],
    )
    liabilities += _post_levies(db, org_id=org_id, pay_run=pay_run, lines=levy_lines)

    for liability in liabilities:
        db.add(liability)
    return liabilities


def is_engine_payslip(payslip: Payslip) -> bool:
    """Whether the payslip came from the engine (its statutory figures are
    its lines) rather than Nigeria's path (its own columns)."""
    return ENGINE_SNAPSHOT_KEY in payslip.derivation


def earnings_of(payslip: Payslip) -> tuple[Earning, ...]:
    """The earnings an engine payslip was calculated on, from its snapshot."""
    snapshot = payslip.derivation.get(ENGINE_SNAPSHOT_KEY)
    inputs = snapshot.get("inputs") if isinstance(snapshot, dict) else None
    earnings = inputs.get("earnings") if isinstance(inputs, dict) else None
    if not isinstance(earnings, list):
        raise TypeError(f"payslip {payslip.id} has no engine snapshot")
    return tuple(
        Earning(EarningCategory(str(earning["category"])), int(earning["amount_minor"]))
        for earning in earnings
    )


def _post_levies(
    db: Session, *, org_id: uuid.UUID, pay_run: PayRun, lines: Sequence[StatutoryLine]
) -> list[StatutoryLiability]:
    charged = [line for line in lines if line.amount_minor > 0]
    if not charged:
        return []
    description = f"Payroll levies for pay run {pay_run.period_start}–{pay_run.period_end}"
    post_journal(
        db,
        org_id=org_id,
        entry_date=pay_run.period_end,
        source_type=JournalSourceType.STATUTORY_ACCRUAL,
        source_id=pay_run.id,
        source_event="levies.accrued",
        description=description,
        lines=[
            PostingLine(
                posting.account,
                debit_minor=posting.debit_minor,
                credit_minor=posting.credit_minor,
                description=description,
                pay_run_id=pay_run.id,
            )
            for posting in build_levy_postings(charged)
        ],
    )
    return [
        _country_liability(
            org_id=org_id,
            pay_run=pay_run,
            key=_LiabilityKey(line.liability_account, line.authority, line.due_date),
            codes=[line.code],
            base_minor=line.base_minor,
            amount_minor=line.amount_minor,
        )
        for line in charged
    ]


def prepare_accounts(db: Session, *, org_id: uuid.UUID, rule_set: CountryRuleSet) -> None:
    """Every account an engine pay run posts to exists in the org's chart
    before it posts, so engine postings are checked against the chart."""
    seed_rule_set_accounts(db, org_id=org_id, rule_set=rule_set)
