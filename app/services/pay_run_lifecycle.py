import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.payroll.tin import MissingTinError, ensure_tin_present
from app.models.employee import Employee, LifecycleState
from app.models.ledger import LedgerEntry
from app.models.loan import Loan, LoanRepayment, LoanStatus
from app.models.pay_run import PayRun, PayRunStatus
from app.models.pay_run_variance_flag import PayRunVarianceFlag, VarianceFlagType
from app.models.payslip import Payslip
from app.models.statutory_liability import LiabilityStatus, StatutoryLiability
from app.services.payroll import outstanding_loan_balance, run_pay_run
from app.services.simulation import SimulationInput, simulate_payslip

# A gross swing at or above this fraction of the previous locked run's
# figure for the same employee gets flagged for a human to look at before
# the run can be validated — not blocked outright, since a real raise or
# bonus should trigger exactly this and still be approvable via override.
_GROSS_SWING_THRESHOLD = 0.30


class PayRunLifecycleError(Exception):
    """A pay-run state transition was attempted out of order, or validate
    found something that needs a human's attention (a missing TIN,
    unacknowledged variance flags) — the API layer translates this to a
    409."""


def _previous_locked_run(db: Session, pay_run: PayRun) -> PayRun | None:
    return db.scalar(
        select(PayRun)
        .where(
            PayRun.org_id == pay_run.org_id,
            PayRun.frequency == pay_run.frequency,
            PayRun.status == PayRunStatus.LOCKED,
            PayRun.period_end < pay_run.period_end,
        )
        .order_by(PayRun.period_end.desc())
        .limit(1)
    )


def _detect_variance(
    db: Session, *, pay_run: PayRun, employees: list[Employee]
) -> list[PayRunVarianceFlag]:
    """Compares this (not-yet-persisted) run against the org's last locked
    run of the same frequency: an employee whose gross would swing 30%+, or
    an employee who was active and paid last time but is missing from this
    run's employee set. No previous locked run of this frequency means
    nothing to compare against — no flags are possible yet.
    """
    previous_run = _previous_locked_run(db, pay_run)
    if previous_run is None:
        return []

    previous_gross_by_employee = {
        employee_id: gross_minor
        for employee_id, gross_minor in db.execute(
            select(Payslip.employee_id, Payslip.gross_minor).where(
                Payslip.pay_run_id == previous_run.id
            )
        ).all()
    }

    current_employee_ids = {employee.id for employee in employees}
    flags: list[PayRunVarianceFlag] = []

    for employee in employees:
        previous_gross = previous_gross_by_employee.get(employee.id)
        if previous_gross is None or previous_gross == 0:
            continue
        computation = simulate_payslip(
            db, employee=employee, scenario=SimulationInput(period_end=pay_run.period_end)
        )
        pct_change = (computation.gross_minor - previous_gross) / previous_gross
        if abs(pct_change) >= _GROSS_SWING_THRESHOLD:
            flags.append(
                PayRunVarianceFlag(
                    org_id=pay_run.org_id,
                    pay_run_id=pay_run.id,
                    employee_id=employee.id,
                    flag_type=VarianceFlagType.GROSS_SWING,
                    detail={
                        "previous_gross_minor": previous_gross,
                        "new_gross_minor": computation.gross_minor,
                        "pct_change": round(pct_change, 4),
                    },
                )
            )

    missing_employee_ids = set(previous_gross_by_employee) - current_employee_ids
    if missing_employee_ids:
        still_active = db.scalars(
            select(Employee).where(
                Employee.id.in_(missing_employee_ids),
                Employee.lifecycle_state == LifecycleState.ACTIVE,
            )
        )
        for employee in still_active:
            flags.append(
                PayRunVarianceFlag(
                    org_id=pay_run.org_id,
                    pay_run_id=pay_run.id,
                    employee_id=employee.id,
                    flag_type=VarianceFlagType.EMPLOYEE_MISSING,
                    detail={
                        "employee_number": employee.employee_number,
                        "previous_pay_run_id": str(previous_run.id),
                    },
                )
            )

    return flags


def validate_pay_run(db: Session, *, pay_run: PayRun, override_variance: bool = False) -> PayRun:
    """draft -> validated. Re-checks TIN against current employee records
    (an employee's TIN can change between draft and validate) and runs
    variance detection. Nothing is persisted as a Payslip/LedgerEntry here
    — only lock_pay_run (via run_pay_run) writes those, so a validate
    re-attempt is always safe to repeat.
    """
    if pay_run.status != PayRunStatus.DRAFT:
        raise PayRunLifecycleError(f"pay run is {pay_run.status.value}, not draft")

    employees = list(db.scalars(select(Employee).where(Employee.id.in_(pay_run.employee_ids))))
    for employee in employees:
        try:
            ensure_tin_present(employee.tin)
        except MissingTinError as exc:
            raise PayRunLifecycleError(
                f"employee {employee.employee_number} has no valid TIN"
            ) from exc

    db.execute(delete(PayRunVarianceFlag).where(PayRunVarianceFlag.pay_run_id == pay_run.id))
    flags = _detect_variance(db, pay_run=pay_run, employees=employees)
    now = datetime.now(UTC)
    if override_variance:
        for flag in flags:
            flag.acknowledged = True
            flag.acknowledged_at = now
    for flag in flags:
        db.add(flag)
    db.flush()

    unacknowledged = [flag for flag in flags if not flag.acknowledged]
    if unacknowledged:
        # Committed here rather than left to the caller's session lifecycle:
        # the API layer turns this into a 409, and an exception propagating
        # out of a request's tenant_session rolls the whole transaction
        # back (see tenant_session's except clause) — without this commit,
        # the flags a caller needs to review via GET .../variance-flags
        # before retrying with override_variance would vanish with it.
        db.commit()
        raise PayRunLifecycleError(
            f"{len(unacknowledged)} unacknowledged variance flag(s) — "
            "review GET /pay-runs/{id}/variance-flags, then retry with override_variance"
        )

    pay_run.status = PayRunStatus.VALIDATED
    pay_run.validated_at = now
    db.add(pay_run)
    return pay_run


def lock_pay_run(
    db: Session, *, org_id: uuid.UUID, pay_run: PayRun, account_id: uuid.UUID
) -> PayRun:
    """validated -> locked. This is where run_pay_run actually executes and
    writes the (append-only) payslips and ledger entries — everything
    before this point was a dry run."""
    if pay_run.status != PayRunStatus.VALIDATED:
        raise PayRunLifecycleError(f"pay run is {pay_run.status.value}, not validated")

    employees = list(db.scalars(select(Employee).where(Employee.id.in_(pay_run.employee_ids))))
    run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=employees)
    pay_run.locked_by = account_id
    db.add(pay_run)
    return pay_run


def mark_pay_run_paid(db: Session, *, pay_run: PayRun, account_id: uuid.UUID) -> PayRun:
    """Records confirmed disbursement. Deliberately not a status — a pay
    run is locked either way, disbursed or not, same reasoning as
    login_code being a projection rather than a state."""
    if pay_run.status != PayRunStatus.LOCKED:
        raise PayRunLifecycleError(f"pay run is {pay_run.status.value}, not locked")
    pay_run.disbursed_at = datetime.now(UTC)
    pay_run.disbursed_by = account_id
    db.add(pay_run)
    return pay_run


def discard_pay_run_draft(db: Session, *, pay_run: PayRun) -> None:
    """draft or validated -> deleted. Safe to hard-delete: nothing is
    persisted as a Payslip/LedgerEntry before lock_pay_run runs, so there's
    nothing append-only to reverse yet."""
    if pay_run.status not in (PayRunStatus.DRAFT, PayRunStatus.VALIDATED):
        raise PayRunLifecycleError(
            f"pay run is {pay_run.status.value} — only a draft or validated run can be discarded, "
            "use reverse for a locked one"
        )
    db.delete(pay_run)


def reverse_pay_run(db: Session, *, org_id: uuid.UUID, pay_run: PayRun) -> PayRun:
    """locked -> reversed. Payslips and ledger entries are append-only, so
    correcting a locked run means posting a compensating journal entry
    (every existing posting mirrored with debit/credit swapped) rather than
    editing or deleting anything — same discipline as every other
    correction in this codebase. The original payslips remain as a
    historical record but stop counting toward cumulative PAYE and
    outstanding loan balances (both filter on PayRun.status == LOCKED).

    Statutory liabilities already FILED or REMITTED for this run are left
    untouched — a real filing with a tax authority isn't something this
    software can safely undo. Still-PENDING ones are deleted, since they
    were never actually sent anywhere.
    """
    if pay_run.status != PayRunStatus.LOCKED:
        raise PayRunLifecycleError(f"pay run is {pay_run.status.value}, not locked")

    original_entries = list(
        db.scalars(select(LedgerEntry).where(LedgerEntry.pay_run_id == pay_run.id))
    )
    reversal_journal_entry_id = uuid.uuid4()
    for entry in original_entries:
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=reversal_journal_entry_id,
                pay_run_id=pay_run.id,
                employee_id=entry.employee_id,
                account=entry.account,
                debit_minor=entry.credit_minor,
                credit_minor=entry.debit_minor,
                description=f"reversal of pay run {pay_run.period_start}–{pay_run.period_end}",
            )
        )

    payslip_ids = list(db.scalars(select(Payslip.id).where(Payslip.pay_run_id == pay_run.id)))
    affected_loan_ids = (
        set(
            db.scalars(
                select(LoanRepayment.loan_id).where(LoanRepayment.payslip_id.in_(payslip_ids))
            )
        )
        if payslip_ids
        else set()
    )

    db.execute(
        delete(StatutoryLiability).where(
            StatutoryLiability.pay_run_id == pay_run.id,
            StatutoryLiability.status == LiabilityStatus.PENDING,
        )
    )

    # Flushed before recomputing loan balances below: outstanding_loan_balance
    # excludes repayments belonging to a REVERSED run, so the status change
    # must be visible to that query first, or every affected loan would
    # still look fully repaid and never get restored to ACTIVE.
    pay_run.status = PayRunStatus.REVERSED
    pay_run.reversed_at = datetime.now(UTC)
    db.add(pay_run)
    db.flush()

    for loan in db.scalars(select(Loan).where(Loan.id.in_(affected_loan_ids))):
        if loan.status == LoanStatus.PAID_OFF and outstanding_loan_balance(db, loan) > 0:
            loan.status = LoanStatus.ACTIVE
            db.add(loan)

    return pay_run
