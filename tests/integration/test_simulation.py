import uuid
from datetime import date

from sqlalchemy import select

from app.core.db import tenant_session
from app.domain.payroll.frequency import PayFrequency
from app.models import Employee, EmploymentType, LedgerEntry, Loan, Organisation, PayRun, Payslip
from app.services.payroll import run_pay_run
from app.services.simulation import SimulationInput, simulate_pay_run, simulate_payslip


def _make_org_and_employee(**overrides: object) -> tuple[uuid.UUID, uuid.UUID]:
    org_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    defaults: dict[str, object] = {
        "id": employee_id,
        "org_id": org_id,
        "employee_number": "EMP-001",
        "full_name": "Ada Okafor",
        "state_of_residence": "Lagos",
        "employment_type": EmploymentType.PERMANENT,
        "date_of_joining": date(2025, 1, 1),
        "tin": "12345678-0001",
        "basic_minor": 300_000_00,
        "housing_minor": 150_000_00,
        "transport_minor": 50_000_00,
        "annual_rent_paid_minor": 0,
        "pay_frequency": PayFrequency.MONTHLY,
    }
    defaults.update(overrides)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name="Test Co"))
        db.flush()
        db.add(Employee(**defaults))
    return org_id, employee_id


def test_simulation_matches_a_real_payslip_for_identical_inputs() -> None:
    """The simulator and the real payslip pipeline share the same pure
    compute_payslip and the same cumulative-history lookup, so simulating
    an employee's normal pay (no overrides) should match what a real pay
    run would have produced for that period."""
    org_id, employee_id = _make_org_and_employee()

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        simulated = simulate_payslip(
            db, employee=employee, scenario=SimulationInput(period_end=date(2026, 1, 31))
        )

    pay_run_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            PayRun(
                id=pay_run_id,
                org_id=org_id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                frequency=PayFrequency.MONTHLY,
            )
        )
        db.flush()
        employee = db.get(Employee, employee_id)
        assert employee is not None
        pay_run = db.get(PayRun, pay_run_id)
        assert pay_run is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        real_payslip = db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)).one()
        assert simulated.gross_minor == real_payslip.gross_minor
        assert simulated.paye_minor == real_payslip.paye_minor
        assert simulated.net_pay_minor == real_payslip.net_minor


def test_simulation_persists_nothing() -> None:
    org_id, employee_id = _make_org_and_employee()

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        simulate_payslip(
            db,
            employee=employee,
            scenario=SimulationInput(period_end=date(2026, 1, 31), basic_minor=900_000_00),
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        assert db.scalar(select(Payslip).where(Payslip.employee_id == employee_id)) is None
        assert db.scalar(select(PayRun).where(PayRun.org_id == org_id)) is None
        assert db.scalar(select(LedgerEntry).where(LedgerEntry.employee_id == employee_id)) is None


def test_simulated_raise_produces_higher_paye_and_uses_real_cumulative_history() -> None:
    org_id, employee_id = _make_org_and_employee()
    pay_run_id = uuid.uuid4()

    # A real January payslip establishes cumulative history.
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            PayRun(
                id=pay_run_id,
                org_id=org_id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                frequency=PayFrequency.MONTHLY,
            )
        )
        db.flush()
        employee = db.get(Employee, employee_id)
        pay_run = db.get(PayRun, pay_run_id)
        assert employee is not None
        assert pay_run is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None

        baseline = simulate_payslip(
            db, employee=employee, scenario=SimulationInput(period_end=date(2026, 2, 28))
        )
        doubled_basic = simulate_payslip(
            db,
            employee=employee,
            scenario=SimulationInput(period_end=date(2026, 2, 28), basic_minor=600_000_00),
        )
        assert doubled_basic.gross_minor > baseline.gross_minor
        assert doubled_basic.paye_minor >= baseline.paye_minor

        # Nothing was persisted from the January run's own simulation calls,
        # so February's simulation still only sees the one real January
        # payslip as prior history — sanity-check via the direct DB count.
        payslip_count = len(
            list(db.scalars(select(Payslip).where(Payslip.employee_id == employee_id)))
        )
        assert payslip_count == 1


def test_simulation_includes_active_loan_deduction_by_default() -> None:
    org_id, employee_id = _make_org_and_employee()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            Loan(
                org_id=org_id,
                employee_id=employee_id,
                principal_minor=60_000_00,
                num_installments=2,
                installment_minor=30_000_00,
                start_date=date(2026, 1, 1),
            )
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None

        with_loan = simulate_payslip(
            db, employee=employee, scenario=SimulationInput(period_end=date(2026, 1, 31))
        )
        without_loan = simulate_payslip(
            db,
            employee=employee,
            scenario=SimulationInput(
                period_end=date(2026, 1, 31), include_active_loan_deduction=False
            ),
        )
        assert with_loan.loan_deduction_minor == 30_000_00
        assert without_loan.loan_deduction_minor == 0
        assert with_loan.net_pay_minor == without_loan.net_pay_minor - 30_000_00


def test_simulate_pay_run_totals_across_employees_with_overrides() -> None:
    org_id, employee_id = _make_org_and_employee()
    employee_id_2 = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            Employee(
                id=employee_id_2,
                org_id=org_id,
                employee_number="EMP-002",
                full_name="Chinedu Eze",
                state_of_residence="Lagos",
                employment_type=EmploymentType.PERMANENT,
                date_of_joining=date(2025, 1, 1),
                tin="12345678-0002",
                basic_minor=300_000_00,
                housing_minor=150_000_00,
                transport_minor=50_000_00,
                pay_frequency=PayFrequency.MONTHLY,
            )
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employees = list(db.scalars(select(Employee).where(Employee.org_id == org_id)))
        result = simulate_pay_run(
            db,
            employees=employees,
            period_end=date(2026, 1, 31),
            overrides_by_employee_id={
                employee_id: SimulationInput(period_end=date(2026, 1, 31), basic_minor=600_000_00)
            },
        )

        assert set(result.by_employee_id) == {employee_id, employee_id_2}
        raised = result.by_employee_id[employee_id]
        unchanged = result.by_employee_id[employee_id_2]
        assert raised.gross_minor > unchanged.gross_minor
        assert result.total_gross_minor == raised.gross_minor + unchanged.gross_minor
        assert result.total_employer_cost_minor == (
            raised.gross_minor
            + raised.pension_employer_minor
            + unchanged.gross_minor
            + unchanged.pension_employer_minor
        )
        assert result.total_net_minor == raised.net_pay_minor + unchanged.net_pay_minor
