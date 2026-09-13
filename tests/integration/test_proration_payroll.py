import uuid
from datetime import date

from sqlalchemy import select

from app.core.db import tenant_session
from app.domain.payroll.frequency import PayFrequency
from app.models import (
    Employee,
    EmploymentType,
    FinalSettlement,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Organisation,
    PayRun,
    PayRunStatus,
    Payslip,
    PublicHoliday,
)
from app.models.employee_history_event import EmployeeHistoryEvent, EmployeeHistoryEventType
from app.services.final_settlement import process_final_settlement
from app.services.payroll import run_pay_run

_BASIC = 220_000
_HOUSING = 0
_TRANSPORT = 0
# January 2026 has 22 working days (Mon-Fri).
_JAN_START = date(2026, 1, 1)
_JAN_END = date(2026, 1, 31)


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
        "basic_minor": _BASIC,
        "housing_minor": _HOUSING,
        "transport_minor": _TRANSPORT,
        "annual_rent_paid_minor": 0,
        "pay_frequency": PayFrequency.MONTHLY,
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


def test_new_hire_mid_period_payslip_is_prorated() -> None:
    # Joins Monday 2026-01-19 — 10 of January's 22 working days are owed.
    org_id, employee_id = _make_org_and_employee(date_of_joining=date(2026, 1, 19))
    pay_run_id = _make_pay_run(org_id, _JAN_START, _JAN_END)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        payslip = db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)).one()
        assert payslip.derivation["inputs"]["prorated"] is True
        assert payslip.derivation["inputs"]["credited_working_days"] == 10
        assert payslip.derivation["inputs"]["total_working_days"] == 22
        assert payslip.derivation["inputs"]["basic_minor"] == 100_000  # 220_000 * 10 / 22
        assert payslip.gross_minor == 100_000


def test_public_holiday_is_excluded_from_both_sides_of_the_ratio() -> None:
    # Same new-hire scenario, but New Year's Day (2026-01-01, a Thursday
    # and otherwise a working day) is registered as a public holiday —
    # total working days drops to 21, credited days are unaffected since
    # the employee joins after it.
    org_id, employee_id = _make_org_and_employee(date_of_joining=date(2026, 1, 19))
    pay_run_id = _make_pay_run(org_id, _JAN_START, _JAN_END)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(PublicHoliday(org_id=org_id, holiday_date=date(2026, 1, 1), name="New Year's Day"))

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        payslip = db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)).one()
        assert payslip.derivation["inputs"]["total_working_days"] == 21
        assert payslip.derivation["inputs"]["credited_working_days"] == 10
        assert payslip.gross_minor == (_BASIC * 10 + 21 // 2) // 21


def test_mid_period_compensation_change_splits_the_payslip() -> None:
    # Raise effective 2026-01-19: 12 working days at the old rate
    # (Jan 1-18), 10 at the new rate (Jan 19-31).
    old_basic = 110_000
    org_id, employee_id = _make_org_and_employee(basic_minor=_BASIC)
    pay_run_id = _make_pay_run(org_id, _JAN_START, _JAN_END)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            EmployeeHistoryEvent(
                org_id=org_id,
                employee_id=employee_id,
                event_type=EmployeeHistoryEventType.COMPENSATION_CHANGE,
                effective_date=date(2026, 1, 19),
                detail={"from": {"basic_minor": old_basic}, "to": {"basic_minor": _BASIC}},
            )
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        payslip = db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)).one()
        expected = (old_basic * 12 + 22 // 2) // 22 + (_BASIC * 10 + 22 // 2) // 22
        assert payslip.derivation["inputs"]["basic_minor"] == expected
        assert payslip.gross_minor == expected


def test_approved_unpaid_leave_excludes_those_working_days() -> None:
    # A full working week (Jan 5-9) of approved unpaid leave inside the
    # 22 working-day period leaves 17 credited days.
    org_id, employee_id = _make_org_and_employee()
    pay_run_id = _make_pay_run(org_id, _JAN_START, _JAN_END)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            LeaveRequest(
                org_id=org_id,
                employee_id=employee_id,
                leave_type=LeaveType.UNPAID,
                status=LeaveStatus.APPROVED,
                start_date=date(2026, 1, 5),
                end_date=date(2026, 1, 9),
                days=5,
            )
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        payslip = db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run_id)).one()
        assert payslip.derivation["inputs"]["credited_working_days"] == 17
        assert payslip.gross_minor == (_BASIC * 17 + 22 // 2) // 22


def test_final_settlement_prorates_the_stub_period_since_last_locked_payslip() -> None:
    # A normal January pay run locks first; termination on 2026-02-10
    # should only pay for the working days from Feb 1 to Feb 10 (a stub
    # period), not a second full month stacked on top of gratuity/leave
    # payout.
    org_id, employee_id = _make_org_and_employee()
    pay_run_id = _make_pay_run(org_id, _JAN_START, _JAN_END)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        pay_run = db.get(PayRun, pay_run_id)
        employee = db.get(Employee, employee_id)
        assert pay_run is not None
        assert employee is not None
        run_pay_run(db, org_id=org_id, pay_run=pay_run, employees=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        settlement = process_final_settlement(
            db,
            org_id=org_id,
            employee=employee,
            termination_date=date(2026, 2, 10),
            gratuity_minor=0,
            leave_days_paid_out=0,
            leave_payout_minor=0,
        )
        settlement_id = settlement.id

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        settlement = db.get(FinalSettlement, settlement_id)
        assert settlement is not None
        payslip = db.get(Payslip, settlement.payslip_id)
        assert payslip is not None
        assert payslip.period_start == date(2026, 2, 1)
        assert payslip.period_end == date(2026, 2, 10)
        # Feb 1-10, 2026 (Sun-Tue) has 7 working days (Feb 1 is a Sunday).
        assert payslip.derivation["inputs"]["total_working_days"] == 7
        assert payslip.derivation["inputs"]["credited_working_days"] == 7
        assert payslip.gross_minor == _BASIC
