"""Payroll analytics, read from payslips on pay runs.

Only locked runs count by default (the same rule as the payroll-cost report,
app/services/reports.py): a draft or validated run's figures aren't final,
and a reversed run's are void. A run belongs to the month of its
period_end. Payslips are limited to the selected country's rule versions,
so every amount is in that country's currency and none are ever added
across currencies. Definitions: docs/analytics-metrics.md §2.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.domain.payroll.run_type import PayRunType
from app.models.employee import Employee, EmploymentType
from app.models.overtime import Overtime, OvertimeStatus
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip
from app.schemas.analytics import Breakdown, Metric, PayrollOut, Trend, Unit
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import (
    NO_DEPARTMENT,
    average,
    breakdown,
    build_meta,
    department_names,
    employee_conditions,
    metric,
    row,
    series,
    trend,
)
from app.services.analytics.filters import AnalyticsFilters, month_keys

HREF = "/analytics/payroll"

_EMPLOYMENT_TYPE_LABELS = {
    EmploymentType.PERMANENT: "Permanent",
    EmploymentType.FIXED_TERM: "Fixed term",
    EmploymentType.PART_TIME: "Part time",
    EmploymentType.INTERN: "Intern",
    EmploymentType.CONSULTANT: "Consultant",
}
_STATUS_LABELS = {
    PayRunStatus.DRAFT: "Draft",
    PayRunStatus.VALIDATED: "Validated",
    PayRunStatus.LOCKED: "Locked",
    PayRunStatus.REVERSED: "Reversed",
}


def run_conditions(filters: AnalyticsFilters, org_id: uuid.UUID) -> list[ColumnElement[bool]]:
    return [
        PayRun.org_id == org_id,
        PayRun.status.in_(filters.pay_run_statuses),
        PayRun.period_end.between(filters.date_from, filters.date_to),
    ]


def _country_rule_versions(filters: AnalyticsFilters) -> ColumnElement[bool]:
    # Rule version IDs are "<country>-<version>" (NG-2026.1).
    return Payslip.rule_version_id.like(f"{filters.country}-%")


def payslip_base(filters: AnalyticsFilters, org_id: uuid.UUID, *columns: Any) -> Select[Any]:
    return (
        select(*columns)
        .select_from(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .join(Employee, Payslip.employee_id == Employee.id)
        .where(
            *run_conditions(filters, org_id),
            _country_rule_versions(filters),
            *employee_conditions(filters),
        )
    )


_REGULAR = PayRun.run_type == PayRunType.REGULAR


def _totals_columns() -> list[Any]:
    return [
        func.coalesce(func.sum(Payslip.gross_minor), 0).label("gross"),
        func.coalesce(func.sum(Payslip.pension_employer_minor), 0).label("employer_pension"),
        func.coalesce(func.sum(Payslip.pension_employee_minor), 0).label("employee_pension"),
        func.coalesce(func.sum(Payslip.nhf_minor), 0).label("nhf"),
        func.coalesce(func.sum(Payslip.paye_minor), 0).label("paye"),
        func.coalesce(func.sum(Payslip.net_minor), 0).label("net"),
        func.count(Payslip.id).label("payslips"),
        func.count(func.distinct(Payslip.employee_id)).label("employees"),
        func.coalesce(func.sum(Payslip.gross_minor).filter(_REGULAR), 0).label("regular_gross"),
        func.count(Payslip.id).filter(_REGULAR).label("regular_payslips"),
    ]


def period_totals(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, int]:
    result = db.execute(payslip_base(filters, org_id, *_totals_columns())).mappings().one()
    return {key: int(value) for key, value in result.items()}


def _derived(totals: dict[str, int]) -> dict[str, float | int | None]:
    statutory = totals["employee_pension"] + totals["nhf"] + totals["paye"]
    return {
        "cost": totals["gross"] + totals["employer_pension"],
        "gross": totals["gross"],
        "net": totals["net"],
        "employer_pension": totals["employer_pension"],
        "deductions": totals["gross"] - totals["net"],
        "statutory": statutory,
        "other_deductions": totals["gross"] - statutory - totals["net"],
        "average_gross": average(totals["regular_gross"], totals["regular_payslips"]),
        "employees": totals["employees"],
        "payslips": totals["payslips"],
    }


def latest_run(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> PayRun | None:
    return db.scalar(
        select(PayRun)
        .where(PayRun.org_id == org_id, PayRun.period_end <= filters.date_to)
        .order_by(PayRun.period_end.desc(), PayRun.created_at.desc())
        .limit(1)
    )


def payroll_kpis(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters, *, overview: bool = False
) -> list[Metric]:
    org_id = access.org_id
    currency = filters.currency
    now = _derived(period_totals(db, org_id, filters))
    previous_filters = filters.comparison()
    before = _derived(period_totals(db, org_id, previous_filters)) if previous_filters else {}
    compare = previous_filters is not None
    run = latest_run(db, org_id, filters)
    status_text = (
        f"{_STATUS_LABELS[run.status]} · period ending {run.period_end.isoformat()}"
        if run is not None
        else "No pay runs yet"
    )

    def money(key: str, label: str, definition: str, *, better: bool | None = None) -> Metric:
        return metric(
            key=key,
            label=label,
            unit=Unit.MONEY,
            value=now[key],
            previous=before.get(key),
            compare=compare,
            currency=currency,
            higher_is_better=better,
            definition=definition,
            href=HREF,
            dataset="pay_runs",
        )

    cost = money(
        "cost",
        "Total payroll cost",
        "Gross pay plus employer pension on the period's locked pay runs: the employer's "
        "cost, the same figure as the payroll-cost report. NSITF and ITF are under Tax & "
        "Compliance.",
    )
    average_gross = money(
        "average_gross",
        "Average gross pay",
        "Gross pay on regular pay runs ÷ the number of payslips on them, so bonus, "
        "13th-month, arrears and off-cycle runs don't distort it.",
    )
    status_metric = metric(
        key="processing_status",
        label="Payroll processing status",
        unit=Unit.TEXT,
        value=None,
        compare=False,
        text_value=status_text,
        definition="The status of the latest pay run whose period ends on or before the "
        "period's last day.",
        href="/payroll",
    )
    if overview:
        return [cost, average_gross, status_metric]
    return [
        cost,
        money("gross", "Gross pay", "Total gross pay on the period's pay runs."),
        money("net", "Net pay", "Total net pay: what employees received after every deduction."),
        money(
            "employer_pension",
            "Employer contributions",
            "Employer pension on the period's payslips. NSITF and ITF are employer "
            "obligations too, recorded as statutory liabilities under Tax & Compliance.",
        ),
        money(
            "deductions",
            "Employee deductions",
            "Gross pay minus net pay: PAYE, employee pension, NHF, and loan, benefit and "
            "union-dues deductions.",
        ),
        average_gross,
        metric(
            key="employees",
            label="Employees paid",
            unit=Unit.COUNT,
            value=now["employees"],
            previous=before.get("employees"),
            compare=compare,
            definition="Distinct employees with a payslip on the period's pay runs.",
            href=HREF,
            dataset="pay_runs",
        ),
        status_metric,
    ]


def cost_trend(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> Trend:
    return _trends(db, access, filters)["cost_trend"]


def _trends(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> dict[str, Trend]:
    org_id = access.org_id
    currency = filters.currency
    months = month_keys(filters.date_from, filters.date_to)
    month = func.to_char(PayRun.period_end, "YYYY-MM").label("month")
    raw = {
        r["month"]: {k: int(v) for k, v in r.items() if k != "month"}
        for r in db.execute(
            payslip_base(filters, org_id, month, *_totals_columns()).group_by(month)
        ).mappings()
    }
    rows = {m: _derived(totals) for m, totals in raw.items()}

    def values(key: str) -> dict[str, float | int | None]:
        return {m: figures[key] for m, figures in rows.items()}

    def raw_values(key: str) -> dict[str, float | int | None]:
        return {m: totals[key] for m, totals in raw.items()}

    overtime_month = func.to_char(PayRun.period_end, "YYYY-MM").label("month")
    overtime = {
        m: int(amount)
        for m, amount in db.execute(
            select(overtime_month, func.coalesce(func.sum(Overtime.amount_minor), 0))
            .select_from(Overtime)
            .join(PayRun, Overtime.pay_run_id == PayRun.id)
            .join(Employee, Overtime.employee_id == Employee.id)
            .where(
                *run_conditions(filters, org_id),
                PayRun.rule_version_id.like(f"{filters.country}-%"),
                Overtime.status == OvertimeStatus.PAID,
                *employee_conditions(filters),
            )
            .group_by(overtime_month)
        ).tuples()
    }
    # A month with no included pay run has no payroll figure, not a zero.
    paid_months = set(rows)
    overtime_values = {m: overtime.get(m, 0) for m in paid_months}

    return {
        "cost_trend": trend(
            key="cost",
            title="Payroll cost",
            unit=Unit.MONEY,
            currency=currency,
            stacked=True,
            series_list=[
                series("gross", "Gross pay", months, values("gross"), missing=None),
                series(
                    "employer_pension",
                    "Employer pension",
                    months,
                    values("employer_pension"),
                    missing=None,
                ),
            ],
            definition="Gross pay and employer pension by the month each pay run's period "
            "ends; together they are the total payroll cost.",
            dataset="pay_runs",
        ),
        "gross_net_trend": trend(
            key="gross_net",
            title="Gross and net pay",
            unit=Unit.MONEY,
            currency=currency,
            series_list=[
                series("gross", "Gross pay", months, values("gross"), missing=None),
                series("net", "Net pay", months, values("net"), missing=None),
            ],
            definition="Gross pay and the net pay left after deductions. Two separate "
            "measures, so not stacked.",
            dataset="pay_runs",
        ),
        "employer_contribution_trend": trend(
            key="employer_contributions",
            title="Employer pension contributions",
            unit=Unit.MONEY,
            currency=currency,
            series_list=[
                series(
                    "employer_pension",
                    "Employer pension",
                    months,
                    values("employer_pension"),
                    missing=None,
                )
            ],
            definition="Employer pension on each month's payslips.",
            dataset="pay_runs",
        ),
        "deduction_trend": trend(
            key="deductions",
            title="Employee deductions",
            unit=Unit.MONEY,
            currency=currency,
            stacked=True,
            series_list=[
                series("paye", "PAYE", months, raw_values("paye"), missing=None),
                series(
                    "employee_pension",
                    "Employee pension",
                    months,
                    raw_values("employee_pension"),
                    missing=None,
                ),
                series("nhf", "NHF", months, raw_values("nhf"), missing=None),
                series(
                    "other_deductions",
                    "Loans, benefits and dues",
                    months,
                    values("other_deductions"),
                    missing=None,
                ),
            ],
            definition="What came out of gross pay, by kind. Their sum is gross minus net.",
            dataset="pay_runs",
        ),
        "overtime_trend": trend(
            key="overtime",
            title="Overtime paid",
            unit=Unit.MONEY,
            currency=currency,
            series_list=[series("overtime", "Overtime", months, overtime_values, missing=None)],
            definition="Approved overtime paid through each month's pay runs (part of gross pay).",
            dataset="pay_runs",
        ),
    }


def _group_breakdowns(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters
) -> dict[str, Breakdown]:
    org_id = access.org_id
    currency = filters.currency
    protect = not access.can_view_individual_pay
    columns = [
        func.coalesce(func.sum(Payslip.gross_minor + Payslip.pension_employer_minor), 0),
        func.count(func.distinct(Payslip.employee_id)),
        func.coalesce(func.sum(Payslip.gross_minor).filter(_REGULAR), 0),
        func.count(Payslip.id).filter(_REGULAR),
        func.count(func.distinct(Payslip.employee_id)).filter(_REGULAR),
    ]
    names = department_names(db, org_id)
    by_department = db.execute(
        payslip_base(filters, org_id, Employee.department_id, *columns).group_by(
            Employee.department_id
        )
    ).tuples()
    cost_rows, average_rows = [], []
    for dept, cost, people, regular_gross, regular_slips, regular_people in by_department:
        label = names.get(dept, NO_DEPARTMENT) if dept else NO_DEPARTMENT
        cost_rows.append(row(dept or "none", label, int(cost), count=people, protect=protect))
        if regular_slips:
            average_rows.append(
                row(
                    dept or "none",
                    label,
                    average(int(regular_gross), regular_slips),
                    count=regular_people,
                    protect=protect,
                )
            )
    by_type = db.execute(
        payslip_base(filters, org_id, Employee.employment_type, *columns[:2]).group_by(
            Employee.employment_type
        )
    ).tuples()
    type_rows = [
        row(kind.value, _EMPLOYMENT_TYPE_LABELS[kind], int(cost), count=people, protect=protect)
        for kind, cost, people in by_type
    ]
    status_rows = db.execute(
        select(PayRun.status, func.count())
        .where(
            PayRun.org_id == org_id,
            PayRun.period_end.between(filters.date_from, filters.date_to),
        )
        .group_by(PayRun.status)
    ).tuples()
    suppression = (
        " A group of fewer than 3 employees is hidden, so no one's pay can be inferred."
        if protect
        else ""
    )
    return {
        "cost_by_department": breakdown(
            key="cost_by_department",
            title="Payroll cost by department",
            unit=Unit.MONEY,
            currency=currency,
            rows=cost_rows,
            definition="Gross pay plus employer pension for the period, by each employee's "
            "current department; the count is employees paid." + suppression,
            dataset="pay_runs",
        ),
        "average_gross_by_department": breakdown(
            key="average_gross_by_department",
            title="Average gross pay by department",
            unit=Unit.MONEY,
            currency=currency,
            rows=average_rows,
            definition="Gross pay on regular runs ÷ payslips on them, by department." + suppression,
            dataset="pay_runs",
        ),
        "cost_by_employment_type": breakdown(
            key="cost_by_employment_type",
            title="Payroll cost by employment type",
            unit=Unit.MONEY,
            currency=currency,
            rows=type_rows,
            definition="Gross pay plus employer pension for the period, by employment type."
            + suppression,
            dataset="pay_runs",
        ),
        "runs_by_status": breakdown(
            key="runs_by_status",
            title="Pay runs by status",
            unit=Unit.COUNT,
            rows=[
                row(status.value, _STATUS_LABELS[status], count, count=count)
                for status, count in status_rows
            ],
            definition="Every pay run whose period ends in the range, whatever its status "
            "(the payroll-status filter does not apply here).",
            dataset="pay_runs",
        ),
    }


def payroll(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> PayrollOut:
    trends = _trends(db, access, filters)
    groups = _group_breakdowns(db, access, filters)
    status_note = (
        "Locked pay runs only."
        if filters.payroll_status == "locked"
        else "Includes validated pay runs that are not yet locked: those figures can still change."
    )
    return PayrollOut(
        meta=build_meta(
            "payroll",
            filters,
            access,
            notes=[
                status_note,
                "Each pay run counts in the month its period ends.",
                (
                    "Departments and employment types are each employee's current values, as in "
                    "the payroll-cost report."
                ),
            ],
        ),
        kpis=payroll_kpis(db, access, filters),
        cost_trend=trends["cost_trend"],
        gross_net_trend=trends["gross_net_trend"],
        employer_contribution_trend=trends["employer_contribution_trend"],
        deduction_trend=trends["deduction_trend"],
        overtime_trend=trends["overtime_trend"],
        cost_by_department=groups["cost_by_department"],
        average_gross_by_department=groups["average_gross_by_department"],
        cost_by_employment_type=groups["cost_by_employment_type"],
        runs_by_status=groups["runs_by_status"],
    )
