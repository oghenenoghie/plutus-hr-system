import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance.engine.postings import build_payslip_postings as build_engine_payslip_postings
from app.compliance.models import RuleVersion
from app.domain.accounting.posting_rules import PostingLine
from app.domain.payroll.benefits import (
    BenefitCandidate,
    is_benefit_active_this_period,
    select_benefit_deductions,
)
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.loans import next_installment_amount
from app.domain.payroll.payslip import compute_payslip
from app.domain.payroll.postings import build_payslip_postings
from app.domain.payroll.proration import PayComponents, ProrationResult, prorate_pay_components
from app.domain.payroll.tin import ensure_tin_present
from app.domain.payroll.union_dues import union_dues_deduction_minor as compute_union_dues_deduction
from app.models.benefit import Benefit
from app.models.employee import Employee
from app.models.journal_entry import JournalSourceType
from app.models.leave import LeaveRequest, LeaveStatus, LeaveType
from app.models.leave_encashment import LeaveEncashmentRequest, LeaveEncashmentStatus
from app.models.loan import Loan, LoanRepayment, LoanStatus
from app.models.overtime import Overtime, OvertimeStatus
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip
from app.models.statutory_liability import StatutoryLiability
from app.models.union_membership import UnionMembership, UnionMembershipStatus
from app.services import engine_payroll
from app.services.employee_history import earliest_compensation_change_in_period
from app.services.jurisdiction import organisation_country, rules_for_organisation, uses_engine
from app.services.posting import post_journal
from app.services.public_holidays import holidays_for_range
from app.services.statutory_liability import generate_liabilities_for_pay_run


def tax_year_start(period_end: date) -> date:
    return date(period_end.year, 1, 1)


def cumulative_totals_before(
    db: Session, employee_id: uuid.UUID, year_start: date
) -> tuple[int, int, int, int, int]:
    """Shared by process_employee_payslip and the what-if simulator
    (app/services/simulation.py) — both need the same real-history figures
    to seed cumulative-annual PAYE, one persisting the result and one not.

    Only payslips under a LOCKED pay run count: a reversed run's payslip
    must not contribute to (or double-count in) year-to-date PAYE — the
    same bug class the pay-run lock lifecycle is otherwise built to avoid.
    """
    prior = db.scalars(
        select(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(Payslip.employee_id == employee_id)
        .where(Payslip.period_end >= year_start)
        .where(PayRun.status == PayRunStatus.LOCKED)
        .order_by(Payslip.period_end)
    ).all()
    return (
        sum(p.gross_minor for p in prior),
        sum(p.pension_employee_minor for p in prior),
        sum(p.nhf_minor for p in prior),
        sum(p.paye_minor for p in prior),
        len(prior),
    )


def active_loan(db: Session, employee_id: uuid.UUID) -> Loan | None:
    """At most one active loan per employee — a service-level rule, not a
    DB constraint (a second loan can't be taken out until the first is
    paid off or cancelled)."""
    return db.scalar(
        select(Loan).where(Loan.employee_id == employee_id, Loan.status == LoanStatus.ACTIVE)
    )


def outstanding_loan_balance(db: Session, loan: Loan) -> int:
    # Postgres SUM() over a bigint column returns numeric, which comes back
    # as a Decimal — cast to int immediately so money stays integer minor
    # units throughout, never Decimal (and stays JSON-serialisable).
    #
    # LoanRepayment is append-only (can't be deleted when a pay run is
    # reversed), so a reversed run's repayment is excluded here by joining
    # through to the pay run's status instead — same reasoning as
    # cumulative_totals_before. The outer joins keep a repayment with no
    # traceable payslip/pay-run counted rather than silently dropped.
    repaid = db.scalar(
        select(func.coalesce(func.sum(LoanRepayment.amount_minor), 0))
        .select_from(LoanRepayment)
        .outerjoin(Payslip, LoanRepayment.payslip_id == Payslip.id)
        .outerjoin(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(
            LoanRepayment.loan_id == loan.id,
            (PayRun.status != PayRunStatus.REVERSED) | (PayRun.id.is_(None)),
        )
    )
    return loan.total_repayable_minor - int(repaid or 0)


class _SharedComputationKwargs(TypedDict):
    """The compute_payslip inputs every pass in process_employee_payslip
    needs identically — gross, pension and NHF never depend on the loan,
    benefit or union-dues deductions, only on these."""

    basic_minor: int
    housing_minor: int
    transport_minor: int
    other_earnings_minor: int
    annual_rent_paid_minor: int
    periods_elapsed_this_year: int
    frequency: PayFrequency
    cumulative_gross_before_minor: int
    cumulative_pension_employee_before_minor: int
    cumulative_nhf_before_minor: int
    cumulative_paye_withheld_before_minor: int
    rules: RuleVersion


@dataclass
class _Period:
    """Everything about one employee's pay period that doesn't depend on the
    country's statutory rules: what's owed (prorated pay, overtime, leave
    encashment) and what could come off net pay afterwards (the loan
    installment, benefits, union dues). Shared by the Nigerian and engine
    payslips."""

    loan: Loan | None
    scheduled_loan_minor: int
    outstanding_loan_before_minor: int
    pending_overtime: list[Overtime]
    overtime_minor: int
    pending_encashments: list[LeaveEncashmentRequest]
    leave_encashment_minor: int
    proration: ProrationResult
    other_earnings_minor: int  # recurring other earnings + one-offs + overtime + encashment
    benefit_candidates: list[BenefitCandidate]
    union_membership: UnionMembership | None


def _gather_period(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    employee: Employee,
    extra_other_earnings_minor: int,
    full_loan_recovery: bool,
) -> _Period:
    loan = active_loan(db, employee.id)
    loan_deduction_minor = 0
    outstanding_before_minor = 0
    if loan is not None:
        outstanding_before_minor = outstanding_loan_balance(db, loan)
        if outstanding_before_minor > 0:
            scheduled = outstanding_before_minor if full_loan_recovery else loan.installment_minor
            loan_deduction_minor = next_installment_amount(outstanding_before_minor, scheduled)

    # Every approved-but-unpaid overtime entry gets swept into the next pay
    # run automatically, same "request -> approval -> next-pay-run payout"
    # shape as the loan deduction above. Taxable but never pensionable
    # (nigeria-statutory-compliance.md §6 — pensionable pay is
    # basic+housing+transport only) — folded in as other_earnings, exactly
    # like final settlement's gratuity/leave payout.
    pending_overtime = list(
        db.scalars(
            select(Overtime).where(
                Overtime.employee_id == employee.id,
                Overtime.status == OvertimeStatus.APPROVED,
                Overtime.pay_run_id.is_(None),
            )
        )
    )
    overtime_minor = sum(entry.amount_minor for entry in pending_overtime)

    # Same automatic pickup for approved-but-unpaid leave encashment —
    # taxable extra earnings, same as final settlement's leave payout.
    pending_encashments = list(
        db.scalars(
            select(LeaveEncashmentRequest).where(
                LeaveEncashmentRequest.employee_id == employee.id,
                LeaveEncashmentRequest.status == LeaveEncashmentStatus.APPROVED,
                LeaveEncashmentRequest.pay_run_id.is_(None),
            )
        )
    )
    leave_encashment_minor = sum(entry.amount_minor for entry in pending_encashments)

    # Working-days proration (app.domain.payroll.proration) — covers a new
    # hire whose date_of_joining falls inside this period, a mid-period
    # compensation change (split at the change's effective_date, old rate
    # before / new rate from then on), and approved unpaid leave inside
    # the period. Only the recurring base components are prorated; the
    # one-off additions below (extra_other_earnings, overtime, leave
    # encashment) are already exactly what's owed for this period and
    # are added on top, unprorated.
    compensation_change = earliest_compensation_change_in_period(
        db,
        employee_id=employee.id,
        period_start=pay_run.period_start,
        period_end=pay_run.period_end,
    )
    prior_components = None
    change_effective_date = None
    if compensation_change is not None:
        change_effective_date = compensation_change.effective_date
        changed_from = compensation_change.detail.get("from", {})
        prior_components = PayComponents(
            basic_minor=changed_from.get("basic_minor", employee.basic_minor),
            housing_minor=changed_from.get("housing_minor", employee.housing_minor),
            transport_minor=changed_from.get("transport_minor", employee.transport_minor),
            other_earnings_minor=changed_from.get(
                "other_earnings_minor", employee.other_earnings_minor
            ),
        )
    unpaid_leave_ranges = tuple(
        (leave.start_date, leave.end_date)
        for leave in db.scalars(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == employee.id,
                LeaveRequest.leave_type == LeaveType.UNPAID,
                LeaveRequest.status == LeaveStatus.APPROVED,
                LeaveRequest.start_date <= pay_run.period_end,
                LeaveRequest.end_date >= pay_run.period_start,
            )
        )
    )
    holidays = holidays_for_range(
        db, org_id=org_id, start=pay_run.period_start, end=pay_run.period_end
    )
    proration = prorate_pay_components(
        period_start=pay_run.period_start,
        period_end=pay_run.period_end,
        hire_date=employee.date_of_joining,
        current=PayComponents(
            basic_minor=employee.basic_minor,
            housing_minor=employee.housing_minor,
            transport_minor=employee.transport_minor,
            other_earnings_minor=employee.other_earnings_minor,
        ),
        prior=prior_components,
        change_effective_date=change_effective_date,
        unpaid_leave_ranges=unpaid_leave_ranges,
        holidays=holidays,
    )

    other_earnings_minor = (
        proration.other_earnings_minor
        + extra_other_earnings_minor
        + overtime_minor
        + leave_encashment_minor
    )

    all_candidates = (
        BenefitCandidate(
            id=benefit.id,
            value_minor=benefit.value_minor,
            frequency=benefit.frequency,
            effective_date=benefit.effective_date,
            end_date=benefit.end_date,
        )
        for benefit in db.scalars(select(Benefit).where(Benefit.employee_id == employee.id))
    )
    benefit_candidates = [
        candidate
        for candidate in all_candidates
        if is_benefit_active_this_period(
            candidate, period_start=pay_run.period_start, period_end=pay_run.period_end
        )
    ]
    active_union_membership = db.scalar(
        select(UnionMembership).where(
            UnionMembership.employee_id == employee.id,
            UnionMembership.status == UnionMembershipStatus.ACTIVE,
        )
    )
    return _Period(
        loan=loan,
        scheduled_loan_minor=loan_deduction_minor,
        outstanding_loan_before_minor=outstanding_before_minor,
        pending_overtime=pending_overtime,
        overtime_minor=overtime_minor,
        pending_encashments=pending_encashments,
        leave_encashment_minor=leave_encashment_minor,
        proration=proration,
        other_earnings_minor=other_earnings_minor,
        benefit_candidates=benefit_candidates,
        union_membership=active_union_membership,
    )


def _record_period_effects(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    payslip: Payslip,
    period: _Period,
    loan_deduction_minor: int,
) -> None:
    """Marks the period's overtime and leave encashment paid and records the
    loan repayment, once the payslip exists to point them at."""
    for entry in period.pending_overtime:
        entry.status = OvertimeStatus.PAID
        entry.pay_run_id = pay_run.id
        db.add(entry)

    for encashment in period.pending_encashments:
        encashment.status = LeaveEncashmentStatus.PAID
        encashment.pay_run_id = pay_run.id
        db.add(encashment)

    loan = period.loan
    if loan is not None and loan_deduction_minor > 0:
        db.add(
            LoanRepayment(
                org_id=org_id,
                loan_id=loan.id,
                payslip_id=payslip.id,
                amount_minor=loan_deduction_minor,
            )
        )
        if period.outstanding_loan_before_minor - loan_deduction_minor <= 0:
            loan.status = LoanStatus.PAID_OFF
            db.add(loan)
        # The session factory disables autoflush, so a caller querying the
        # repayment (e.g. final settlement summing recovered loan amounts)
        # right after this call wouldn't otherwise see it yet.
        db.flush()


def process_employee_payslip(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    employee: Employee,
    extra_other_earnings_minor: int = 0,
    full_loan_recovery: bool = False,
) -> Payslip:
    """Compute and persist one employee's payslip for a pay run, plus its
    balanced ledger postings and any loan repayment. Raises MissingTinError
    (never silently skips) if the employee has no valid TIN — the caller's
    transaction (a tenant_session) rolls back on that exception, so no
    partial run persists.

    extra_other_earnings_minor lets a caller (final settlement) add taxable
    one-off amounts like gratuity or leave payout to this period without
    mutating the employee's stored recurring pay. full_loan_recovery
    deducts the entire outstanding balance instead of the scheduled
    installment — used to close out a loan at exit.
    """
    ensure_tin_present(employee.tin)
    if extra_other_earnings_minor < 0:
        raise ValueError("extra_other_earnings_minor must not be negative")

    country = organisation_country(db, org_id)
    if uses_engine(country):
        return _process_engine_payslip(
            db,
            org_id=org_id,
            country=country,
            pay_run=pay_run,
            employee=employee,
            extra_other_earnings_minor=extra_other_earnings_minor,
            full_loan_recovery=full_loan_recovery,
        )

    rules = rules_for_organisation(db, org_id, pay_run.period_end)
    year_start = tax_year_start(pay_run.period_end)
    (
        cumulative_gross_before,
        cumulative_pension_employee_before,
        cumulative_nhf_before,
        cumulative_paye_before,
        periods_elapsed_before,
    ) = cumulative_totals_before(db, employee.id, year_start)

    period = _gather_period(
        db,
        org_id=org_id,
        pay_run=pay_run,
        employee=employee,
        extra_other_earnings_minor=extra_other_earnings_minor,
        full_loan_recovery=full_loan_recovery,
    )
    loan = period.loan
    loan_deduction_minor = period.scheduled_loan_minor
    outstanding_before_minor = period.outstanding_loan_before_minor
    pending_overtime = period.pending_overtime
    overtime_minor = period.overtime_minor
    pending_encashments = period.pending_encashments
    leave_encashment_minor = period.leave_encashment_minor
    proration = period.proration
    other_earnings_minor = period.other_earnings_minor

    shared_computation_kwargs: _SharedComputationKwargs = {
        "basic_minor": proration.basic_minor,
        "housing_minor": proration.housing_minor,
        "transport_minor": proration.transport_minor,
        "other_earnings_minor": other_earnings_minor,
        "annual_rent_paid_minor": employee.annual_rent_paid_minor,
        "periods_elapsed_this_year": periods_elapsed_before + 1,
        "frequency": employee.pay_frequency,
        "cumulative_gross_before_minor": cumulative_gross_before,
        "cumulative_pension_employee_before_minor": cumulative_pension_employee_before,
        "cumulative_nhf_before_minor": cumulative_nhf_before,
        "cumulative_paye_withheld_before_minor": cumulative_paye_before,
        "rules": rules,
    }

    # Deduction priority is statutory -> loans -> benefits -> union dues
    # (each stage's budget is what the previous stage left over), and a
    # stage that can't be covered yields rather than partially deducting
    # or blowing up the whole computation — same "skip whole enrollment"
    # rule benefits already use below, now applied to the loan step too.
    # This needs its own pass (loan_deduction_minor=0) because net pay
    # before the loan is itself an output of gross/pension/NHF/PAYE.
    if loan_deduction_minor > 0:
        net_before_loan = compute_payslip(**shared_computation_kwargs).net_pay_minor
        if loan_deduction_minor > net_before_loan:
            loan_deduction_minor = 0

    # Benefits need a first pass to know how much net is actually left to
    # deduct from — each active benefit is then applied in effective_date
    # order, skipping (never partially deducting) any that wouldn't fit,
    # same "skip whole enrollment if it can't be covered" rule as
    # hr-payroll uses. This can't be folded into a single pass: the budget
    # itself is this computation's own output.
    net_before_benefits = compute_payslip(
        **shared_computation_kwargs,
        loan_deduction_minor=loan_deduction_minor,
    ).net_pay_minor

    applied_benefits, benefit_deduction_minor = select_benefit_deductions(
        period.benefit_candidates, available_net_minor=net_before_benefits
    )

    # Union dues are checked last (statutory -> loans -> benefits -> union
    # dues), against whatever's left after benefits — pure subtraction
    # from net_before_benefits rather than another compute_payslip call,
    # since neither benefits nor dues touch PAYE/pension/NHF/gross at all.
    net_before_union_dues = net_before_benefits - benefit_deduction_minor
    active_union_membership = period.union_membership
    union_dues_minor = (
        compute_union_dues_deduction(
            active_union_membership.monthly_dues_minor, available_net_minor=net_before_union_dues
        )
        if active_union_membership is not None
        else 0
    )

    computation = compute_payslip(
        **shared_computation_kwargs,
        loan_deduction_minor=loan_deduction_minor,
        benefit_deduction_minor=benefit_deduction_minor,
        union_dues_deduction_minor=union_dues_minor,
    )

    payslip = Payslip(
        org_id=org_id,
        pay_run_id=pay_run.id,
        employee_id=employee.id,
        period_start=pay_run.period_start,
        period_end=pay_run.period_end,
        gross_minor=computation.gross_minor,
        pensionable_pay_minor=computation.pensionable_pay_minor,
        pension_employee_minor=computation.pension_employee_minor,
        pension_employer_minor=computation.pension_employer_minor,
        nhf_minor=computation.nhf_minor,
        paye_minor=computation.paye_minor,
        net_minor=computation.net_pay_minor,
        cumulative_chargeable_income_minor=computation.cumulative_chargeable_income_minor,
        rule_version_id=rules.id,
        derivation={
            "inputs": {
                "basic_minor": proration.basic_minor,
                "housing_minor": proration.housing_minor,
                "transport_minor": proration.transport_minor,
                "other_earnings_minor": other_earnings_minor,
                "prorated": proration.is_prorated,
                "credited_working_days": proration.credited_working_days,
                "total_working_days": proration.total_working_days,
                "extra_other_earnings_minor": extra_other_earnings_minor,
                "annual_rent_paid_minor": employee.annual_rent_paid_minor,
                "periods_elapsed_this_year": periods_elapsed_before + 1,
                "frequency": employee.pay_frequency.value,
                "cumulative_gross_before_minor": cumulative_gross_before,
                "cumulative_pension_employee_before_minor": cumulative_pension_employee_before,
                "cumulative_nhf_before_minor": cumulative_nhf_before,
                "cumulative_paye_withheld_before_minor": cumulative_paye_before,
                "loan_id": str(loan.id) if loan is not None else None,
                "outstanding_loan_before_minor": outstanding_before_minor,
                "full_loan_recovery": full_loan_recovery,
                "overtime_minor": overtime_minor,
                "overtime_entry_ids": [str(entry.id) for entry in pending_overtime],
                "leave_encashment_minor": leave_encashment_minor,
                "leave_encashment_request_ids": [str(entry.id) for entry in pending_encashments],
                "benefit_deduction_minor": benefit_deduction_minor,
                "applied_benefit_ids": [str(b.benefit_id) for b in applied_benefits],
                "union_dues_deduction_minor": union_dues_minor,
                "union_membership_id": (
                    str(active_union_membership.id) if active_union_membership is not None else None
                ),
                "rule_version_id": rules.id,
            },
            "outputs": asdict(computation),
        },
    )
    db.add(payslip)
    db.flush()  # need payslip.id for the LoanRepayment/Overtime FKs below

    _record_period_effects(
        db,
        org_id=org_id,
        pay_run=pay_run,
        payslip=payslip,
        period=period,
        loan_deduction_minor=loan_deduction_minor,
    )

    description = (
        f"payslip for {employee.employee_number}, {pay_run.period_start}–{pay_run.period_end}"
    )
    post_journal(
        db,
        org_id=org_id,
        # The accounting date of a payroll posting is the end of the period
        # it pays for, not the moment the run happened to be locked.
        entry_date=pay_run.period_end,
        source_type=JournalSourceType.PAYROLL,
        source_id=payslip.id,
        source_event="payslip.locked",
        description=description,
        lines=[
            PostingLine(
                account=posting.account,
                debit_minor=posting.debit_minor,
                credit_minor=posting.credit_minor,
                description=description,
                employee_id=employee.id,
                department_id=employee.department_id,
                pay_run_id=pay_run.id,
            )
            for posting in build_payslip_postings(computation)
        ],
        # Payroll has always posted without consulting the chart, and an org
        # that never seeded one must still be able to lock a run (audit P3);
        # the chart also lacks two accounts payroll posts to (audit P1).
        validate_chart=False,
    )

    return payslip


def _process_engine_payslip(
    db: Session,
    *,
    org_id: uuid.UUID,
    country: str,
    pay_run: PayRun,
    employee: Employee,
    extra_other_earnings_minor: int,
    full_loan_recovery: bool,
) -> Payslip:
    """The payslip for an organisation whose country is on the engine. The
    statutory lines come from the country's approved rule set; what comes
    off net pay after them (the loan installment, benefits, union dues) is
    applied in the same order and with the same "skip what doesn't fit"
    rule as Nigeria's. Refuses (TaxConfigurationError) before touching
    anything if the country has no approved rule set for the period."""
    rule_set = engine_payroll.rule_set_for(country, pay_run.period_end)
    year_start = engine_payroll.tax_year_start(pay_run.period_end, rule_set.tax_year_start_month)
    year_to_date, periods_before = engine_payroll.year_to_date_before(db, employee.id, year_start)
    period = _gather_period(
        db,
        org_id=org_id,
        pay_run=pay_run,
        employee=employee,
        extra_other_earnings_minor=extra_other_earnings_minor,
        full_loan_recovery=full_loan_recovery,
    )
    proration = period.proration
    result = engine_payroll.compute(
        rule_set,
        employee=employee,
        period_end=pay_run.period_end,
        earnings=engine_payroll.earnings_for(
            basic_minor=proration.basic_minor,
            housing_minor=proration.housing_minor,
            transport_minor=proration.transport_minor,
            recurring_other_minor=proration.other_earnings_minor,
            overtime_minor=period.overtime_minor,
            one_off_minor=extra_other_earnings_minor + period.leave_encashment_minor,
        ),
        year_to_date=year_to_date,
        periods_elapsed_this_year=periods_before + 1,
    )

    statutory_net_minor = result.net_pay_minor
    loan_deduction_minor = period.scheduled_loan_minor
    if loan_deduction_minor > statutory_net_minor:
        loan_deduction_minor = 0
    applied_benefits, benefit_deduction_minor = select_benefit_deductions(
        period.benefit_candidates, available_net_minor=statutory_net_minor - loan_deduction_minor
    )
    union_dues_minor = (
        compute_union_dues_deduction(
            period.union_membership.monthly_dues_minor,
            available_net_minor=statutory_net_minor
            - loan_deduction_minor
            - benefit_deduction_minor,
        )
        if period.union_membership is not None
        else 0
    )
    net_minor = (
        statutory_net_minor - loan_deduction_minor - benefit_deduction_minor - union_dues_minor
    )

    payslip = Payslip(
        org_id=org_id,
        pay_run_id=pay_run.id,
        employee_id=employee.id,
        period_start=pay_run.period_start,
        period_end=pay_run.period_end,
        gross_minor=result.gross_minor,
        # Nigeria's own columns; an engine payslip's statutory lines are in
        # payslip_statutory_lines, and its income tax is kept here too.
        pensionable_pay_minor=0,
        pension_employee_minor=0,
        pension_employer_minor=0,
        nhf_minor=0,
        paye_minor=engine_payroll.income_tax_minor(result),
        net_minor=net_minor,
        cumulative_chargeable_income_minor=result.income_tax.taxable_income_minor,
        rule_version_id=rule_set.id,
        derivation={
            "inputs": {
                "rule_set_id": rule_set.id,
                "prorated": proration.is_prorated,
                "credited_working_days": proration.credited_working_days,
                "total_working_days": proration.total_working_days,
                "extra_other_earnings_minor": extra_other_earnings_minor,
                "loan_id": str(period.loan.id) if period.loan is not None else None,
                "outstanding_loan_before_minor": period.outstanding_loan_before_minor,
                "full_loan_recovery": full_loan_recovery,
                "overtime_minor": period.overtime_minor,
                "overtime_entry_ids": [str(entry.id) for entry in period.pending_overtime],
                "leave_encashment_minor": period.leave_encashment_minor,
                "leave_encashment_request_ids": [
                    str(entry.id) for entry in period.pending_encashments
                ],
                "applied_benefit_ids": [str(b.benefit_id) for b in applied_benefits],
                "union_membership_id": (
                    str(period.union_membership.id) if period.union_membership is not None else None
                ),
            },
            "outputs": {
                "gross_minor": result.gross_minor,
                "statutory_net_minor": statutory_net_minor,
                "loan_deduction_minor": loan_deduction_minor,
                "benefit_deduction_minor": benefit_deduction_minor,
                "union_dues_deduction_minor": union_dues_minor,
                "net_pay_minor": net_minor,
            },
            engine_payroll.ENGINE_SNAPSHOT_KEY: result.snapshot(),
            engine_payroll.ENGINE_PERIOD_KEY: engine_payroll.period_figures(result),
        },
    )
    db.add(payslip)
    db.flush()  # need payslip.id for the lines and the period's effects
    engine_payroll.record_lines(db, org_id=org_id, payslip=payslip, result=result)
    _record_period_effects(
        db,
        org_id=org_id,
        pay_run=pay_run,
        payslip=payslip,
        period=period,
        loan_deduction_minor=loan_deduction_minor,
    )

    engine_payroll.prepare_accounts(db, org_id=org_id, rule_set=rule_set)
    description = (
        f"payslip for {employee.employee_number}, {pay_run.period_start}–{pay_run.period_end}"
    )
    post_journal(
        db,
        org_id=org_id,
        entry_date=pay_run.period_end,
        source_type=JournalSourceType.PAYROLL,
        source_id=payslip.id,
        source_event="payslip.locked",
        description=description,
        lines=[
            PostingLine(
                account=posting.account,
                debit_minor=posting.debit_minor,
                credit_minor=posting.credit_minor,
                description=description,
                employee_id=employee.id,
                department_id=employee.department_id,
                pay_run_id=pay_run.id,
            )
            for posting in build_engine_payslip_postings(
                result,
                other_deductions=(
                    ("employee_loan_receivable", loan_deduction_minor),
                    ("benefit_deductions_recovered", benefit_deduction_minor),
                    ("union_dues_payable", union_dues_minor),
                ),
            )
        ],
    )
    return payslip


def generate_pay_run_liabilities(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    payslips: Sequence[Payslip],
    employees_by_id: dict[uuid.UUID, Employee],
) -> list[StatutoryLiability]:
    """The run's statutory liabilities: Nigeria's schemes, or an engine
    country's lines and payroll levies."""
    country = organisation_country(db, org_id)
    if uses_engine(country):
        rule_set = engine_payroll.rule_set_for(country, pay_run.period_end)
        engine_payroll.prepare_accounts(db, org_id=org_id, rule_set=rule_set)
        return engine_payroll.generate_liabilities(
            db, org_id=org_id, pay_run=pay_run, payslips=payslips, rule_set=rule_set
        )
    rules = rules_for_organisation(db, org_id, pay_run.period_end)
    return generate_liabilities_for_pay_run(
        db,
        org_id=org_id,
        pay_run=pay_run,
        payslips=list(payslips),
        employees_by_id=employees_by_id,
        rules=rules,
    )


def run_pay_run(
    db: Session, *, org_id: uuid.UUID, pay_run: PayRun, employees: Sequence[Employee]
) -> PayRun:
    """Process every employee in a pay run and lock it. The whole run is one
    transaction (the caller's tenant_session): a single missing TIN or
    computation error rolls back every payslip and ledger entry the run
    would otherwise have created — never a partially-processed run.

    This is the one place payslips/ledger entries are actually written —
    both are append-only (see their model docstrings), so nothing about a
    pay run is genuinely permanent before this runs. The draft/validate
    steps (app/services/pay_run_lifecycle.py) only ever dry-run compute via
    simulate_payslip; lock_pay_run is what calls this for real.
    """
    payslips = [
        process_employee_payslip(
            db,
            org_id=org_id,
            pay_run=pay_run,
            employee=employee,
            extra_other_earnings_minor=pay_run.extra_earnings_minor.get(str(employee.id), 0),
        )
        for employee in employees
    ]

    pay_run.employee_count = len(payslips)
    pay_run.gross_minor = sum(p.gross_minor for p in payslips)
    pay_run.net_minor = sum(p.net_minor for p in payslips)
    pay_run.rule_version_id = payslips[0].rule_version_id if payslips else None
    pay_run.status = PayRunStatus.LOCKED
    pay_run.locked_at = datetime.now(UTC)
    db.add(pay_run)

    if payslips:
        generate_pay_run_liabilities(
            db,
            org_id=org_id,
            pay_run=pay_run,
            payslips=payslips,
            employees_by_id={employee.id: employee for employee in employees},
        )

    return pay_run
