import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.employee import Employee
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip


@dataclass(frozen=True)
class PayrollCostLine:
    """One (locked pay run, department) cell of the cross-run cost report.
    department_id/department_name are None for employees not assigned to
    any department — grouped together rather than dropped, since that
    headcount is still real payroll cost."""

    pay_run_id: uuid.UUID
    period_start: date
    period_end: date
    department_id: uuid.UUID | None
    department_name: str | None
    employee_count: int
    gross_minor: int
    employer_cost_minor: int
    net_minor: int


def payroll_cost_by_department(
    db: Session,
    org_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[PayrollCostLine]:
    """Payroll cost trended across every locked pay run, broken down by
    department — hr-payroll's cross-run department cost-centre report.
    Only LOCKED runs count: a draft/validated run's figures aren't final
    yet, and a reversed run's are void (same reasoning as
    cumulative_totals_before excluding both).
    """
    query = (
        select(
            PayRun.id,
            PayRun.period_start,
            PayRun.period_end,
            Employee.department_id,
            Department.name,
            func.count(Payslip.id),
            func.coalesce(func.sum(Payslip.gross_minor), 0),
            func.coalesce(func.sum(Payslip.gross_minor + Payslip.pension_employer_minor), 0),
            func.coalesce(func.sum(Payslip.net_minor), 0),
        )
        .select_from(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .join(Employee, Payslip.employee_id == Employee.id)
        .outerjoin(Department, Employee.department_id == Department.id)
        .where(PayRun.org_id == org_id, PayRun.status == PayRunStatus.LOCKED)
        .group_by(
            PayRun.id,
            PayRun.period_start,
            PayRun.period_end,
            Employee.department_id,
            Department.name,
        )
        .order_by(PayRun.period_end, Department.name)
    )
    if from_date is not None:
        query = query.where(PayRun.period_end >= from_date)
    if to_date is not None:
        query = query.where(PayRun.period_end <= to_date)

    return [
        PayrollCostLine(
            pay_run_id=pay_run_id,
            period_start=period_start,
            period_end=period_end,
            department_id=department_id,
            department_name=department_name,
            employee_count=employee_count,
            gross_minor=int(gross_minor),
            employer_cost_minor=int(employer_cost_minor),
            net_minor=int(net_minor),
        )
        for (
            pay_run_id,
            period_start,
            period_end,
            department_id,
            department_name,
            employee_count,
            gross_minor,
            employer_cost_minor,
            net_minor,
        ) in db.execute(query).all()
    ]
