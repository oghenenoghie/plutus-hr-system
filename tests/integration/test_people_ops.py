import uuid
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.core.db import tenant_session
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.loans import compute_equal_installments
from app.models import (
    Employee,
    EmploymentType,
    FinalSettlement,
    LeaveRequest,
    LeaveType,
    LifecycleState,
    Loan,
    LoanRepayment,
    LoanStatus,
    Organisation,
    PayRun,
    PayRunStatus,
    Payslip,
)
from app.services.final_settlement import process_final_settlement
from app.services.leave import InsufficientLeaveBalanceError, approve_leave_request, leave_balance
from app.services.payroll import process_employee_payslip, run_pay_run


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
        "annual_leave_entitlement_days": 20,
    }
    defaults.update(overrides)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name="Test Co"))
        db.flush()
        db.add(Employee(**defaults))
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


def test_loan_deduction_reduces_net_pay_and_pays_off() -> None:
    org_id, employee_id = _make_org_and_employee()
    loan_id = uuid.uuid4()
    installments = compute_equal_installments(90_000_00, 3)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            Loan(
                id=loan_id,
                org_id=org_id,
                employee_id=employee_id,
                principal_minor=90_000_00,
                num_installments=3,
                installment_minor=installments[0],
                start_date=date(2026, 1, 1),
            )
        )

    for month in range(1, 4):
        pay_run_id = _make_pay_run(org_id, date(2026, month, 1), date(2026, month, 28))
        with tenant_session(org_id, uuid.uuid4(), "admin") as db:
            pay_run = db.get(PayRun, pay_run_id)
            employee = db.get(Employee, employee_id)
            assert pay_run is not None
            assert employee is not None
            run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        loan = db.get(Loan, loan_id)
        assert loan is not None
        assert loan.status == LoanStatus.PAID_OFF

        repayments = list(db.scalars(select(LoanRepayment).where(LoanRepayment.loan_id == loan_id)))
        assert len(repayments) == 3
        assert sum(r.amount_minor for r in repayments) == 90_000_00

        payslips = list(
            db.scalars(
                select(Payslip)
                .where(Payslip.employee_id == employee_id)
                .order_by(Payslip.period_end)
            )
        )
        assert len(payslips) == 3
        # Net pay in every period is reduced by exactly that period's installment.
        for payslip, installment in zip(payslips, installments, strict=True):
            gross_minus_statutory = (
                payslip.gross_minor
                - payslip.pension_employee_minor
                - payslip.nhf_minor
                - payslip.paye_minor
            )
            assert payslip.net_minor == gross_minus_statutory - installment


def test_leave_approval_enforces_balance() -> None:
    org_id, employee_id = _make_org_and_employee(annual_leave_entitlement_days=5)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert leave_balance(db, employee, date(2026, 3, 1)) == 5

        request = LeaveRequest(
            org_id=org_id,
            employee_id=employee_id,
            leave_type=LeaveType.ANNUAL,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 10),
            days=7,
        )
        db.add(request)
        db.flush()

        with pytest.raises(InsufficientLeaveBalanceError):
            approve_leave_request(db, employee=employee, request=request)


def test_leave_approval_succeeds_within_balance_and_reduces_it() -> None:
    org_id, employee_id = _make_org_and_employee(annual_leave_entitlement_days=20)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None

        request = LeaveRequest(
            org_id=org_id,
            employee_id=employee_id,
            leave_type=LeaveType.ANNUAL,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 5),
            days=5,
        )
        db.add(request)
        db.flush()
        approve_leave_request(db, employee=employee, request=request)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert leave_balance(db, employee, date(2026, 4, 1)) == 15


def test_final_settlement_taxes_gratuity_and_recovers_full_loan() -> None:
    org_id, employee_id = _make_org_and_employee()
    loan_id = uuid.uuid4()

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            Loan(
                id=loan_id,
                org_id=org_id,
                employee_id=employee_id,
                principal_minor=90_000_00,
                num_installments=6,
                installment_minor=15_000_00,
                start_date=date(2026, 1, 1),
            )
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        settlement = process_final_settlement(
            db,
            org_id=org_id,
            employee=employee,
            termination_date=date(2026, 6, 30),
            gratuity_minor=1_000_000_00,
            leave_days_paid_out=10,
            leave_payout_minor=166_670_00,
        )
        settlement_id = settlement.id

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        settlement = db.get(FinalSettlement, settlement_id)
        assert settlement is not None
        assert settlement.outstanding_loan_recovered_minor == 90_000_00

        payslip = db.get(Payslip, settlement.payslip_id)
        assert payslip is not None
        # Gratuity + leave payout are taxable other_earnings, so gross
        # includes them and PAYE is charged on the enlarged amount.
        assert payslip.gross_minor == 500_000_00 + 1_000_000_00 + 166_670_00
        assert payslip.paye_minor > 0
        assert settlement.net_settlement_minor == payslip.net_minor

        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.lifecycle_state == LifecycleState.TERMINATED

        loan = db.get(Loan, loan_id)
        assert loan is not None
        assert loan.status == LoanStatus.PAID_OFF


def test_loan_repayments_are_append_only() -> None:
    org_id, employee_id = _make_org_and_employee()
    loan_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            Loan(
                id=loan_id,
                org_id=org_id,
                employee_id=employee_id,
                principal_minor=30_000_00,
                num_installments=1,
                installment_minor=30_000_00,
                start_date=date(2026, 1, 1),
            )
        )

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
        db.execute(text("DELETE FROM loan_repayments"))
