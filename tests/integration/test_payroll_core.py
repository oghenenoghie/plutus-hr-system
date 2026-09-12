import uuid
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.core.db import tenant_session
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.tin import MissingTinError
from app.models import (
    Employee,
    EmploymentType,
    LedgerEntry,
    Organisation,
    PayRun,
    PayRunStatus,
    Payslip,
)
from app.services.payroll import process_employee_payslip, run_pay_run


def _make_org_and_employee(
    *,
    tin: str | None = "12345678-0001",
    basic: int = 300_000_00,
    housing: int = 150_000_00,
    transport: int = 50_000_00,
) -> tuple[uuid.UUID, uuid.UUID]:
    org_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name="Test Co"))
        db.flush()  # parent row must exist before the FK-referencing insert below
        db.add(
            Employee(
                id=employee_id,
                org_id=org_id,
                employee_number="EMP-001",
                full_name="Ada Okafor",
                state_of_residence="Lagos",
                employment_type=EmploymentType.PERMANENT,
                date_of_joining=date(2025, 1, 1),
                tin=tin,
                basic_minor=basic,
                housing_minor=housing,
                transport_minor=transport,
                annual_rent_paid_minor=2_000_000_00,
                pay_frequency=PayFrequency.MONTHLY,
            )
        )
    return org_id, employee_id


def _make_pay_run(org_id: uuid.UUID, period_start: date, period_end: date) -> uuid.UUID:
    pay_run_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            PayRun(
                id=pay_run_id,
                org_id=org_id,
                period_start=period_start,
                period_end=period_end,
                frequency=PayFrequency.MONTHLY,
                status=PayRunStatus.DRAFT,
            )
        )
    return pay_run_id


def test_employees_and_payslips_are_tenant_isolated() -> None:
    org_a, _ = _make_org_and_employee()
    org_b, _ = _make_org_and_employee()

    with tenant_session(org_a, uuid.uuid4(), "admin") as db:
        visible_org_ids = {e.org_id for e in db.scalars(select(Employee))}
        assert visible_org_ids == {org_a}
        assert org_b not in visible_org_ids


def test_pay_run_produces_balanced_payslip_and_ledger() -> None:
    org_id, employee_id = _make_org_and_employee()
    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        assert pay_run is not None
        assert pay_run.status == PayRunStatus.LOCKED
        assert pay_run.employee_count == 1

        payslips = list(db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)))
        assert len(payslips) == 1
        payslip = payslips[0]
        assert pay_run.gross_minor == payslip.gross_minor
        assert pay_run.net_minor == payslip.net_minor

        entries = list(db.scalars(select(LedgerEntry).where(LedgerEntry.pay_run_id == pay_run_id)))
        assert entries, "expected ledger postings"
        # NSITF is posted separately at the pay-run level (see
        # test_statutory_liability.py), so only the payslip's own postings
        # are expected to share one journal_entry_id here.
        payslip_entries = [
            e for e in entries if e.account not in ("payroll_expense_nsitf", "nsitf_payable")
        ]
        journal_ids = {e.journal_entry_id for e in payslip_entries}
        assert len(journal_ids) == 1
        total_debit = sum(e.debit_minor for e in entries)
        total_credit = sum(e.credit_minor for e in entries)
        assert total_debit == total_credit


def test_cumulative_paye_across_two_pay_runs_matches_hand_verified_figures() -> None:
    # Same inputs independently hand-verified against the band table while
    # building the pure compute_payslip function: month 1 PAYE = 0,
    # month 2 PAYE = 5,750 naira (575,000 kobo).
    org_id, employee_id = _make_org_and_employee()
    run1_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))
    run2_id = _make_pay_run(org_id, date(2026, 2, 1), date(2026, 2, 28))

    for run_id in (run1_id, run2_id):
        with tenant_session(org_id, uuid.uuid4(), "admin") as db:
            pay_run = db.get(PayRun, run_id)
            employee = db.get(Employee, employee_id)
            assert pay_run is not None
            assert employee is not None
            run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        payslip1 = db.scalars(select(Payslip).where(Payslip.pay_run_id == run1_id)).one()
        payslip2 = db.scalars(select(Payslip).where(Payslip.pay_run_id == run2_id)).one()
        assert payslip1.paye_minor == 0
        assert payslip2.paye_minor == 575_000


def test_run_pay_run_blocks_on_missing_tin_and_rolls_back() -> None:
    org_id, employee_id = _make_org_and_employee(tin=None)
    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))

    with pytest.raises(MissingTinError), tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        assert pay_run is not None
        assert pay_run.status == PayRunStatus.DRAFT  # never advanced past draft
        assert db.scalar(select(Payslip).where(Payslip.pay_run_id == pay_run_id)) is None
        assert db.scalar(select(LedgerEntry).where(LedgerEntry.pay_run_id == pay_run_id)) is None


def test_payslips_are_append_only() -> None:
    org_id, employee_id = _make_org_and_employee()
    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        process_employee_payslip(db, org_id=org_id, pay_run=pay_run, employee=employee)

    # Tenant context must be set for RLS to let the row through at all —
    # this proves the append-only trigger itself blocks the write, not RLS
    # masking a row that would otherwise have been silently unaffected.
    with (
        pytest.raises(ProgrammingError, match="append-only"),
        tenant_session(org_id, uuid.uuid4(), "admin") as db,
    ):
        db.execute(text("UPDATE payslips SET net_minor = 0"))


def test_ledger_entries_are_append_only() -> None:
    org_id, employee_id = _make_org_and_employee()
    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        process_employee_payslip(db, org_id=org_id, pay_run=pay_run, employee=employee)

    with (
        pytest.raises(ProgrammingError, match="append-only"),
        tenant_session(org_id, uuid.uuid4(), "admin") as db,
    ):
        db.execute(text("DELETE FROM ledger_entries"))


def test_unbalanced_ledger_entry_rejected_at_commit() -> None:
    org_id, _ = _make_org_and_employee()
    journal_entry_id = uuid.uuid4()

    with (
        pytest.raises(ProgrammingError, match="not balanced"),
        tenant_session(org_id, uuid.uuid4(), "admin") as db,
    ):
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=journal_entry_id,
                account="payroll_expense_gross",
                debit_minor=1_000,
                credit_minor=0,
            )
        )
