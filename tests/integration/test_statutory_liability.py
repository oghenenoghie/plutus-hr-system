import uuid
from datetime import date

from sqlalchemy import select

from app.core.db import tenant_session
from app.domain.payroll.frequency import PayFrequency
from app.models import (
    BankAccount,
    Employee,
    EmploymentType,
    LedgerEntry,
    LiabilityScheme,
    LiabilityStatus,
    Organisation,
    PayRun,
    PayRunStatus,
    Payslip,
    StatutoryLiability,
)
from app.services.disbursement import generate_disbursement_file
from app.services.payroll import run_pay_run
from app.services.statutory_liability import mark_liability_filed, mark_liability_remitted


def _make_org_and_employees(states: list[str]) -> tuple[uuid.UUID, list[uuid.UUID]]:
    org_id = uuid.uuid4()
    employee_ids = []
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name="Test Co"))
        db.flush()
        for i, state in enumerate(states):
            employee_id = uuid.uuid4()
            employee_ids.append(employee_id)
            db.add(
                Employee(
                    id=employee_id,
                    org_id=org_id,
                    employee_number=f"EMP-{i:03d}",
                    full_name=f"Employee {i}",
                    state_of_residence=state,
                    employment_type=EmploymentType.PERMANENT,
                    date_of_joining=date(2025, 1, 1),
                    tin=f"TIN-{i}",
                    basic_minor=300_000_00,
                    housing_minor=150_000_00,
                    transport_minor=50_000_00,
                    pay_frequency=PayFrequency.MONTHLY,
                )
            )
    return org_id, employee_ids


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


def test_run_pay_run_generates_nsitf_pension_nhf_liabilities() -> None:
    org_id, employee_ids = _make_org_and_employees(["Lagos"])
    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employees = list(db.scalars(select(Employee).where(Employee.id.in_(employee_ids))))
        assert pay_run is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=employees)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        liabilities = list(
            db.scalars(
                select(StatutoryLiability).where(StatutoryLiability.pay_run_id == pay_run_id)
            )
        )
        by_scheme = {liability.scheme: liability for liability in liabilities}

        assert LiabilityScheme.PENSION in by_scheme
        assert by_scheme[LiabilityScheme.PENSION].amount_minor == 40_000_00 + 50_000_00
        assert by_scheme[LiabilityScheme.PENSION].base_minor == 500_000_00  # pensionable pay

        assert LiabilityScheme.NHF in by_scheme
        assert by_scheme[LiabilityScheme.NHF].amount_minor == 7_500_00
        assert by_scheme[LiabilityScheme.NHF].base_minor == 300_000_00  # basic only

        assert LiabilityScheme.NSITF in by_scheme
        assert by_scheme[LiabilityScheme.NSITF].amount_minor == 5_000_00  # 1% of 500,000
        assert by_scheme[LiabilityScheme.NSITF].due_date == date(2026, 2, 16)

        # NSITF gets its own balanced ledger posting (pay-run-level, not
        # per-payslip like PAYE/pension/NHF).
        nsitf_entries = list(
            db.scalars(
                select(LedgerEntry).where(
                    LedgerEntry.pay_run_id == pay_run_id,
                    LedgerEntry.account.in_(["payroll_expense_nsitf", "nsitf_payable"]),
                )
            )
        )
        assert sum(e.debit_minor for e in nsitf_entries) == sum(
            e.credit_minor for e in nsitf_entries
        )
        assert sum(e.debit_minor for e in nsitf_entries) == 5_000_00


def test_paye_liability_split_by_employee_state_of_residence() -> None:
    org_id, employee_ids = _make_org_and_employees(["Lagos", "Lagos", "Rivers"])

    # Give the employees different pay so each owes PAYE this period —
    # bump gross well above the tax-free threshold via other_earnings.
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        for employee_id in employee_ids:
            employee = db.get(Employee, employee_id)
            assert employee is not None
            employee.other_earnings_minor = 2_000_000_00
            db.add(employee)

    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employees = list(db.scalars(select(Employee).where(Employee.id.in_(employee_ids))))
        assert pay_run is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=employees)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        paye_liabilities = list(
            db.scalars(
                select(StatutoryLiability).where(
                    StatutoryLiability.pay_run_id == pay_run_id,
                    StatutoryLiability.scheme == LiabilityScheme.PAYE,
                )
            )
        )
        by_state = {liability.state: liability.amount_minor for liability in paye_liabilities}
        assert set(by_state) == {"Lagos", "Rivers"}
        # Two Lagos employees with identical pay -> Lagos liability is
        # exactly double one Rivers employee's.
        assert by_state["Lagos"] == 2 * by_state["Rivers"]

        payslips_total_paye = sum(
            p.paye_minor
            for p in db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id))
        )
        assert sum(by_state.values()) == payslips_total_paye


def test_mark_liability_filed_then_remitted() -> None:
    org_id, employee_ids = _make_org_and_employees(["Lagos"])
    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employees = list(db.scalars(select(Employee).where(Employee.id.in_(employee_ids))))
        assert pay_run is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=employees)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        liability = db.scalars(
            select(StatutoryLiability).where(
                StatutoryLiability.pay_run_id == pay_run_id,
                StatutoryLiability.scheme == LiabilityScheme.NHF,
            )
        ).one()
        mark_liability_filed(db, liability)
        liability_id = liability.id

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        liability = db.get(StatutoryLiability, liability_id)
        assert liability is not None
        assert liability.status == LiabilityStatus.FILED
        assert liability.filed_at is not None
        mark_liability_remitted(db, liability, reference="FMBN-REF-001")

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        liability = db.get(StatutoryLiability, liability_id)
        assert liability is not None
        assert liability.status == LiabilityStatus.REMITTED
        assert liability.remittance_reference == "FMBN-REF-001"


def test_disbursement_file_skips_unverified_accounts() -> None:
    org_id, employee_ids = _make_org_and_employees(["Lagos", "Lagos"])
    pay_run_id = _make_pay_run(org_id, date(2026, 1, 1), date(2026, 1, 31))

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            BankAccount(
                org_id=org_id,
                employee_id=employee_ids[0],
                bank_name="First Bank",
                account_number="1234567890",
                account_name="Employee 0",
                verified=True,
            )
        )
        db.add(
            BankAccount(
                org_id=org_id,
                employee_id=employee_ids[1],
                bank_name="GTBank",
                account_number="0987654321",
                account_name="Employee 1",
                verified=False,
            )
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employees = list(db.scalars(select(Employee).where(Employee.id.in_(employee_ids))))
        assert pay_run is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=employees)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        result = generate_disbursement_file(db, pay_run_id=pay_run_id)
        assert "EMP-000" in result.csv_content
        assert "EMP-001" not in result.csv_content
        assert result.skipped_employee_numbers == ("EMP-001",)
        assert result.total_minor > 0
