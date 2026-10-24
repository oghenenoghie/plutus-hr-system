"""Leave analytics. Requests count in the month they start; balances and
utilisation follow app/services/leave.approved_days_taken exactly, so they
match what the leave screens show. Definitions: docs/analytics-metrics.md §4.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee, LifecycleState
from app.models.leave import LeaveRequest, LeaveStatus, LeaveType
from app.models.leave_encashment import LeaveEncashmentRequest, LeaveEncashmentStatus
from app.schemas.analytics import LeaveOut, Metric, Unit
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import (
    NO_DEPARTMENT,
    average,
    breakdown,
    build_meta,
    department_names,
    employee_conditions,
    metric,
    percent,
    row,
    series,
    trend,
)
from app.services.analytics.filters import AnalyticsFilters, month_keys

HREF = "/analytics/leave"

_TYPE_LABELS = {
    LeaveType.ANNUAL: "Annual",
    LeaveType.SICK: "Sick",
    LeaveType.MATERNITY: "Maternity",
    LeaveType.PATERNITY: "Paternity",
    LeaveType.UNPAID: "Unpaid",
}
_STATUS_LABELS = {
    LeaveStatus.PENDING: "Pending",
    LeaveStatus.APPROVED: "Approved",
    LeaveStatus.REJECTED: "Rejected",
    LeaveStatus.CANCELLED: "Cancelled",
}
_BALANCE_BANDS = (
    ("0", "None left", 0, 0),
    ("1to5", "1–5 days", 1, 5),
    ("6to10", "6–10 days", 6, 10),
    ("11to15", "11–15 days", 11, 15),
    ("16plus", "16 days or more", 16, None),
)


def _requests(filters: AnalyticsFilters, org_id: uuid.UUID, *columns: Any) -> Any:
    return (
        select(*columns)
        .select_from(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .where(
            LeaveRequest.org_id == org_id,
            LeaveRequest.start_date.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
    )


def pending_now(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters
) -> tuple[int, date | None]:
    """Requests awaiting a decision today, whatever their dates."""
    count, oldest = db.execute(
        select(func.count(), func.min(func.date(LeaveRequest.created_at)))
        .select_from(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .where(
            LeaveRequest.org_id == org_id,
            LeaveRequest.status == LeaveStatus.PENDING,
            *employee_conditions(filters),
        )
    ).one()
    return int(count), oldest


def _period(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, int]:
    approved = LeaveRequest.status == LeaveStatus.APPROVED
    result = (
        db.execute(
            _requests(
                filters,
                org_id,
                func.count().label("requests"),
                func.count().filter(approved).label("approved"),
                func.count().filter(LeaveRequest.status == LeaveStatus.REJECTED).label("rejected"),
                func.coalesce(func.sum(LeaveRequest.days).filter(approved), 0).label(
                    "approved_days"
                ),
            )
        )
        .mappings()
        .one()
    )
    return {key: int(value) for key, value in result.items()}


def balances(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> list[dict[str, Any]]:
    """Each in-scope, not-terminated employee's entitlement, days counted
    against it in the leave year of the period's last day, and balance.
    The same rule as services.leave.approved_days_taken: approved leave of
    any type starting in that year, plus approved or paid encashments
    requested in it; the balance never goes below zero."""
    year_start = date(filters.date_to.year, 1, 1)
    taken = (
        select(
            LeaveRequest.employee_id.label("employee_id"),
            func.sum(LeaveRequest.days).label("days"),
        )
        .where(
            LeaveRequest.org_id == org_id,
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date >= year_start,
        )
        .group_by(LeaveRequest.employee_id)
        .subquery("taken")
    )
    encashed = (
        select(
            LeaveEncashmentRequest.employee_id.label("employee_id"),
            func.sum(LeaveEncashmentRequest.days).label("days"),
        )
        .where(
            LeaveEncashmentRequest.org_id == org_id,
            LeaveEncashmentRequest.status.in_(
                (LeaveEncashmentStatus.APPROVED, LeaveEncashmentStatus.PAID)
            ),
            LeaveEncashmentRequest.requested_date >= year_start,
        )
        .group_by(LeaveEncashmentRequest.employee_id)
        .subquery("encashed")
    )
    used = func.coalesce(taken.c.days, 0) + func.coalesce(encashed.c.days, 0)
    stmt = (
        select(
            Employee.id,
            Employee.department_id,
            Employee.annual_leave_entitlement_days,
            used.label("used"),
        )
        .outerjoin(taken, taken.c.employee_id == Employee.id)
        .outerjoin(encashed, encashed.c.employee_id == Employee.id)
        .where(
            Employee.org_id == org_id,
            Employee.lifecycle_state != LifecycleState.TERMINATED,
            *employee_conditions(filters),
        )
    )
    return [
        {
            "employee_id": employee_id,
            "department_id": department_id,
            "entitlement": entitlement,
            "used": int(used_days),
            "balance": max(entitlement - int(used_days), 0),
        }
        for employee_id, department_id, entitlement, used_days in db.execute(stmt).tuples()
    ]


def leave_kpis(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters, *, overview: bool = False
) -> list[Metric]:
    org_id = access.org_id
    pending, oldest = pending_now(db, org_id, filters)
    pending_metric = metric(
        key="pending_requests",
        label="Outstanding leave requests",
        unit=Unit.COUNT,
        value=pending,
        compare=False,
        higher_is_better=False,
        definition="Leave requests awaiting a decision today, whatever dates they are for.",
        href=HREF,
        dataset="leave_requests",
        note=f"Oldest submitted {oldest.day} {oldest:%b %Y}" if oldest else None,
    )
    if overview:
        return [pending_metric]
    now = _period(db, org_id, filters)
    previous_filters = filters.comparison()
    before = _period(db, org_id, previous_filters) if previous_filters else {}
    compare = previous_filters is not None
    rows = balances(db, org_id, filters)
    return [
        metric(
            key="requests",
            label="Leave requests",
            unit=Unit.COUNT,
            value=now["requests"],
            previous=before.get("requests"),
            compare=compare,
            definition="Requests whose leave starts in the period, in any status.",
            href=HREF,
            dataset="leave_requests",
        ),
        metric(
            key="approved_days",
            label="Approved leave days",
            unit=Unit.DAYS,
            value=now["approved_days"],
            previous=before.get("approved_days"),
            compare=compare,
            definition="Days on approved requests starting in the period (all leave types).",
            href=HREF,
            dataset="leave_requests",
        ),
        metric(
            key="approval_rate",
            label="Approval rate",
            unit=Unit.PERCENT,
            value=percent(now["approved"], now["approved"] + now["rejected"]),
            previous=percent(before["approved"], before["approved"] + before["rejected"])
            if before
            else None,
            compare=compare,
            definition="Approved ÷ (approved + rejected) requests starting in the period; "
            "pending and cancelled requests are left out.",
            href=HREF,
            dataset="leave_requests",
        ),
        pending_metric,
        metric(
            key="average_balance",
            label="Average leave balance",
            unit=Unit.DAYS,
            value=average(sum(r["balance"] for r in rows), len(rows)),
            compare=False,
            definition=f"Mean remaining annual leave for {filters.date_to.year}, across current "
            "employees, by the same rule as the leave screens.",
            href=HREF,
        ),
    ]


def leave(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> LeaveOut:
    org_id = access.org_id
    months = month_keys(filters.date_from, filters.date_to)
    approved = LeaveRequest.status == LeaveStatus.APPROVED

    by_status = [
        row(status.value, _STATUS_LABELS[status], count, count=count)
        for status, count in db.execute(
            _requests(filters, org_id, LeaveRequest.status, func.count()).group_by(
                LeaveRequest.status
            )
        ).tuples()
    ]
    by_type = [
        row(kind.value, _TYPE_LABELS[kind], int(days), count=requests)
        for kind, days, requests in db.execute(
            _requests(
                filters, org_id, LeaveRequest.leave_type, func.sum(LeaveRequest.days), func.count()
            )
            .where(approved)
            .group_by(LeaveRequest.leave_type)
        ).tuples()
    ]
    month = func.to_char(LeaveRequest.start_date, "YYYY-MM")
    monthly: dict[LeaveType, dict[str, int]] = {}
    for kind, key, days in db.execute(
        _requests(filters, org_id, LeaveRequest.leave_type, month, func.sum(LeaveRequest.days))
        .where(approved)
        .group_by(LeaveRequest.leave_type, month)
    ).tuples():
        monthly.setdefault(kind, {})[key] = int(days)

    rows = balances(db, org_id, filters)
    names = department_names(db, org_id)
    per_department: dict[uuid.UUID | None, list[int]] = {}
    for r in rows:
        totals = per_department.setdefault(r["department_id"], [0, 0, 0])
        totals[0] += r["used"]
        totals[1] += r["entitlement"]
        totals[2] += 1
    utilisation = [
        row(
            dept or "none",
            names.get(dept, NO_DEPARTMENT) if dept else NO_DEPARTMENT,
            percent(used, entitlement),
            count=people,
        )
        for dept, (used, entitlement, people) in per_department.items()
        if entitlement
    ]
    bands = []
    for key, label, low, high in _BALANCE_BANDS:
        count = sum(
            1 for r in rows if r["balance"] >= low and (high is None or r["balance"] <= high)
        )
        bands.append(row(key, label, count, count=count))

    return LeaveOut(
        meta=build_meta(
            "leave",
            filters,
            access,
            notes=[
                "A request counts in the month its leave starts.",
                (
                    f"Balances and utilisation are for the {filters.date_to.year} leave year, "
                    "as the leave screens compute them: approved leave of any type and "
                    "approved encashments count against the annual entitlement."
                ),
            ],
        ),
        kpis=leave_kpis(db, access, filters),
        by_status=breakdown(
            key="by_status",
            title="Leave requests by status",
            unit=Unit.COUNT,
            rows=by_status,
            definition="Requests whose leave starts in the period, by their current status.",
            dataset="leave_requests",
        ),
        days_by_type=breakdown(
            key="days_by_type",
            title="Approved leave days by type",
            unit=Unit.DAYS,
            rows=by_type,
            definition="Days on approved requests starting in the period; the count is requests.",
            dataset="leave_requests",
        ),
        monthly_trend=trend(
            key="monthly",
            title="Approved leave days by month",
            unit=Unit.DAYS,
            stacked=True,
            series_list=[
                series(kind.value, _TYPE_LABELS[kind], months, monthly.get(kind, {}))
                for kind in LeaveType
                if kind in monthly
            ],
            definition="Days on approved requests, by the month the leave starts and leave type.",
            dataset="leave_requests",
        ),
        utilisation_by_department=breakdown(
            key="utilisation_by_department",
            title="Leave utilisation by department",
            unit=Unit.PERCENT,
            rows=utilisation,
            definition=f"Days counted against entitlement in {filters.date_to.year} ÷ total "
            "annual entitlement × 100, for current employees; the count is employees.",
        ),
        balance_bands=breakdown(
            key="balance_bands",
            title="Leave balance distribution",
            unit=Unit.COUNT,
            rows=bands,
            definition=f"Current employees by remaining annual leave for {filters.date_to.year}.",
            sort=False,
        ),
    )
