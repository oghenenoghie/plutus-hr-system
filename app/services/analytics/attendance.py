"""Attendance analytics, measured against rostered shifts.

The roster (shift_roster_entries) is the only record of who was expected to
work when, and each shift has its own start and end, so no single schedule
is assumed. A rostered shift on a public holiday, or on a day covered by the
employee's approved leave, is left out of the denominator. Clock-in times
are compared with the shift start in Lagos time (WAT). Definitions:
docs/analytics-metrics.md §3.
"""

import uuid
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    Float,
    Integer,
    Time,
    and_,
    case,
    cast,
    func,
    literal,
    select,
    text,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql import Subquery

from app.models.attendance_record import AttendanceRecord
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveStatus
from app.models.overtime import Overtime, OvertimeStatus
from app.models.public_holiday import PublicHoliday
from app.models.shift import Shift
from app.models.shift_roster_entry import ShiftRosterEntry
from app.schemas.analytics import AttendanceOut, Metric, Unit
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import (
    NO_DEPARTMENT,
    NO_LOCATION,
    average,
    breakdown,
    build_meta,
    department_names,
    employee_conditions,
    location_names,
    metric,
    percent,
    row,
    series,
    trend,
)
from app.services.analytics.filters import AnalyticsFilters, month_keys

HREF = "/analytics/attendance"
LOCAL_TZ = "Africa/Lagos"
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _hours(interval: ColumnElement[Any]) -> ColumnElement[Any]:
    return cast(func.extract("epoch", interval), Float) / 3600.0


def rostered_shifts(filters: AnalyticsFilters, org_id: uuid.UUID) -> Subquery:
    """One row per rostered shift in the period, with whether it counts
    toward the rate and how it went."""
    shift_length = case(
        (Shift.end_time > Shift.start_time, Shift.end_time - Shift.start_time),
        else_=Shift.end_time - Shift.start_time + text("interval '24 hours'"),
    )
    # Holidays and approved-leave days as two small pre-filtered sets joined
    # on the date, not a correlated EXISTS per rostered shift: the per-row
    # form scans every leave request for every shift (minutes, not
    # milliseconds, on a large organisation).
    holidays = (
        select(PublicHoliday.holiday_date.label("day"))
        .where(
            PublicHoliday.org_id == org_id,
            PublicHoliday.holiday_date.between(filters.date_from, filters.date_to),
        )
        .distinct()
        .subquery("holidays")
    )
    leave_day = cast(
        func.generate_series(
            func.greatest(LeaveRequest.start_date, filters.date_from),
            func.least(LeaveRequest.end_date, filters.date_to),
            text("interval '1 day'"),
        ),
        Date,
    )
    leave_days = (
        select(LeaveRequest.employee_id.label("employee_id"), leave_day.label("day"))
        .where(
            LeaveRequest.org_id == org_id,
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date <= filters.date_to,
            LeaveRequest.end_date >= filters.date_from,
        )
        .distinct()
        .subquery("leave_days")
    )
    on_holiday = holidays.c.day.is_not(None)
    on_leave = leave_days.c.day.is_not(None)
    attended = AttendanceRecord.clock_in_at.is_not(None)
    local_clock_in = cast(func.timezone(LOCAL_TZ, AttendanceRecord.clock_in_at), Time)
    return (
        select(
            ShiftRosterEntry.employee_id.label("employee_id"),
            ShiftRosterEntry.work_date.label("work_date"),
            Employee.department_id.label("department_id"),
            Employee.branch_id.label("branch_id"),
            (~on_holiday & ~on_leave).label("counted"),
            attended.label("attended"),
            and_(attended, local_clock_in > Shift.start_time).label("late"),
            _hours(shift_length).label("scheduled_hours"),
            case(
                (
                    AttendanceRecord.clock_out_at.is_not(None),
                    _hours(AttendanceRecord.clock_out_at - AttendanceRecord.clock_in_at),
                ),
                else_=literal(None),
            ).label("actual_hours"),
        )
        .select_from(ShiftRosterEntry)
        .join(Employee, ShiftRosterEntry.employee_id == Employee.id)
        .join(Shift, ShiftRosterEntry.shift_id == Shift.id)
        .outerjoin(
            AttendanceRecord,
            and_(
                AttendanceRecord.employee_id == ShiftRosterEntry.employee_id,
                AttendanceRecord.work_date == ShiftRosterEntry.work_date,
            ),
        )
        .outerjoin(holidays, holidays.c.day == ShiftRosterEntry.work_date)
        .outerjoin(
            leave_days,
            and_(
                leave_days.c.employee_id == ShiftRosterEntry.employee_id,
                leave_days.c.day == ShiftRosterEntry.work_date,
            ),
        )
        .where(
            ShiftRosterEntry.org_id == org_id,
            ShiftRosterEntry.work_date.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
        .subquery("rostered")
    )


def _aggregates(shifts: Subquery) -> list[Any]:
    counted = shifts.c.counted
    return [
        func.count().filter(counted).label("expected"),
        func.count().filter(counted & shifts.c.attended).label("attended"),
        func.count().filter(counted & shifts.c.late).label("late"),
        func.count().filter(~counted).label("excluded"),
        func.coalesce(func.sum(shifts.c.scheduled_hours).filter(counted), 0).label(
            "scheduled_hours"
        ),
        func.coalesce(func.sum(shifts.c.actual_hours).filter(counted & shifts.c.attended), 0).label(
            "actual_hours"
        ),
        func.count(shifts.c.actual_hours).filter(counted & shifts.c.attended).label("timed"),
    ]


_AGGREGATE_KEYS = (
    "expected",
    "attended",
    "late",
    "excluded",
    "scheduled_hours",
    "actual_hours",
    "timed",
)


def _overtime_hours(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters, *, by_month: bool
) -> Any:
    month = func.to_char(Overtime.work_date, "YYYY-MM")
    columns: list[Any] = [func.coalesce(func.sum(Overtime.hours), 0)]
    stmt = (
        select(*([month] if by_month else []), *columns)
        .select_from(Overtime)
        .join(Employee, Overtime.employee_id == Employee.id)
        .where(
            Overtime.org_id == org_id,
            Overtime.status.in_((OvertimeStatus.APPROVED, OvertimeStatus.PAID)),
            Overtime.work_date.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
    )
    if by_month:
        return {key: float(hours) for key, hours in db.execute(stmt.group_by(month)).tuples()}
    return float(db.scalar(stmt) or 0)


def _figures(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters, totals: dict[str, Any]
) -> dict[str, Any]:
    rate = percent(totals["attended"], totals["expected"])
    figures = {
        **totals,
        "rate": rate,
        "absence_rate": None if rate is None else round(100 - rate, 2),
        "late_rate": percent(totals["late"], totals["attended"]),
        "overtime_hours": _overtime_hours(db, org_id, filters, by_month=False),
        "average_hours": average(float(totals["actual_hours"]), totals["timed"]),
    }
    if not totals["expected"] and not totals["excluded"]:
        # No roster at all in the period: lateness isn't measurable, so it
        # is None rather than a zero to compare against.
        figures.update(late=None, excluded=None)
    return figures


def period_figures(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, Any]:
    shifts = rostered_shifts(filters, org_id)
    totals: dict[str, Any] = dict(db.execute(select(*_aggregates(shifts))).mappings().one())
    return _figures(db, org_id, filters, totals)


def _grouped(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, Any]:
    """The period's totals and its month, department, location and weekday
    groups from one pass over the roster (GROUPING SETS), instead of a scan
    per grouping."""
    shifts = rostered_shifts(filters, org_id)
    keys = {
        "month": func.to_char(shifts.c.work_date, "YYYY-MM"),
        "department": shifts.c.department_id,
        "location": shifts.c.branch_id,
        "weekday": cast(func.extract("isodow", shifts.c.work_date), Integer),
    }
    stmt = select(
        *(column.label(name) for name, column in keys.items()),
        *(func.grouping(column).label(f"grouping_{name}") for name, column in keys.items()),
        *_aggregates(shifts),
    ).group_by(func.grouping_sets(*keys.values(), text("()")))
    groups: dict[str, Any] = {name: {} for name in keys}
    for r in db.execute(stmt).mappings():
        grouped_by = [name for name in keys if r[f"grouping_{name}"] == 0]
        figures = {key: r[key] for key in _AGGREGATE_KEYS}
        if grouped_by:
            groups[grouped_by[0]][r[grouped_by[0]]] = figures
        else:
            groups["total"] = figures
    return groups


def attendance_kpis(
    db: Session,
    access: AnalyticsAccess,
    filters: AnalyticsFilters,
    *,
    overview: bool = False,
    totals: dict[str, Any] | None = None,
) -> list[Metric]:
    """`totals`: the period's aggregates when the caller already has them
    (the section's grouped query), saving a scan."""
    org_id = access.org_id
    now = (
        period_figures(db, org_id, filters)
        if totals is None
        else _figures(db, org_id, filters, totals)
    )
    previous_filters = filters.comparison()
    before = period_figures(db, org_id, previous_filters) if previous_filters else {}
    compare = previous_filters is not None
    no_roster = (
        "No rostered shifts in the period, so attendance can't be measured."
        if not now["expected"]
        else None
    )
    rate = metric(
        key="attendance_rate",
        label="Attendance rate",
        unit=Unit.PERCENT,
        value=now["rate"],
        previous=before.get("rate"),
        compare=compare,
        higher_is_better=True,
        definition="Rostered shifts the employee clocked in for ÷ rostered shifts × 100. "
        "Shifts on public holidays or approved leave are left out of both.",
        href=HREF,
        dataset="attendance",
        note=no_roster,
    )
    if overview:
        return [rate]
    return [
        rate,
        metric(
            key="absence_rate",
            label="Absence rate",
            unit=Unit.PERCENT,
            value=now["absence_rate"],
            previous=before.get("absence_rate"),
            compare=compare,
            higher_is_better=False,
            definition="Rostered shifts with no clock-in ÷ rostered shifts × 100 (100 − the "
            "attendance rate), on the same basis.",
            href=HREF,
            dataset="attendance",
            note=no_roster,
        ),
        metric(
            key="late_arrivals",
            label="Late arrivals",
            unit=Unit.COUNT,
            value=now["late"],
            previous=before.get("late"),
            compare=compare,
            higher_is_better=False,
            definition="Attended shifts where the clock-in (Lagos time) was after the shift's "
            "start time. There is no grace period: none is configured in the application.",
            href=HREF,
            dataset="attendance",
        ),
        metric(
            key="overtime_hours",
            label="Overtime hours",
            unit=Unit.HOURS,
            value=now["overtime_hours"],
            previous=before.get("overtime_hours"),
            compare=compare,
            definition="Approved or paid overtime hours with a work date in the period.",
            href=HREF,
        ),
        metric(
            key="average_hours",
            label="Average hours per shift",
            unit=Unit.HOURS,
            value=now["average_hours"],
            previous=before.get("average_hours"),
            compare=compare,
            definition="Clock-out minus clock-in, averaged over attended shifts that have both.",
            href=HREF,
            dataset="attendance",
        ),
        metric(
            key="excluded_shifts",
            label="Shifts on holidays or leave",
            unit=Unit.COUNT,
            value=now["excluded"],
            previous=before.get("excluded"),
            compare=compare,
            definition="Rostered shifts left out of the rate because they fell on a public "
            "holiday or the employee's approved leave.",
            href=HREF,
            dataset="attendance",
        ),
    ]


def attendance(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> AttendanceOut:
    org_id = access.org_id
    months = month_keys(filters.date_from, filters.date_to)
    groups = _grouped(db, org_id, filters)

    by_month = groups["month"]
    rate = {m: percent(r["attended"], r["expected"]) for m, r in by_month.items()}
    absence = {m: None if v is None else round(100 - v, 2) for m, v in rate.items()}
    late = {m: r["late"] for m, r in by_month.items()}
    scheduled = {m: round(float(r["scheduled_hours"]), 2) for m, r in by_month.items()}
    actual = {m: round(float(r["actual_hours"]), 2) for m, r in by_month.items()}

    departments = department_names(db, org_id)
    locations = location_names(db, org_id)
    by_department = [
        row(
            key or "none",
            departments.get(key, NO_DEPARTMENT) if key else NO_DEPARTMENT,
            percent(r["attended"], r["expected"]),
            count=r["expected"],
        )
        for key, r in groups["department"].items()
        if r["expected"]
    ]
    by_location = [
        row(
            key or "none",
            locations.get(key, NO_LOCATION) if key else NO_LOCATION,
            percent(r["attended"], r["expected"]),
            count=r["expected"],
        )
        for key, r in groups["location"].items()
        if r["expected"]
    ]
    weekday = groups["weekday"]
    by_weekday = [
        row(
            str(day),
            _WEEKDAYS[day - 1],
            percent(weekday[day]["attended"], weekday[day]["expected"]) if day in weekday else None,
            count=weekday[day]["expected"] if day in weekday else 0,
        )
        for day in range(1, 8)
    ]

    rate_definition = (
        "Attended ÷ rostered shifts × 100, excluding shifts on public holidays or approved leave."
    )
    return AttendanceOut(
        meta=build_meta(
            "attendance",
            filters,
            access,
            notes=[
                (
                    "Attendance is measured against rostered shifts; days without a roster "
                    "entry are not counted either way."
                ),
                "Clock-in times are compared with the shift start in Lagos time (WAT).",
            ],
        ),
        kpis=attendance_kpis(db, access, filters, totals=groups["total"]),
        rate_trend=trend(
            key="attendance_rate",
            title="Attendance and absence rate",
            unit=Unit.PERCENT,
            series_list=[
                series("attendance", "Attendance rate", months, rate, missing=None),
                series("absence", "Absence rate", months, absence, missing=None),
            ],
            definition=rate_definition + " A month with no rostered shifts has no rate.",
            dataset="attendance",
        ),
        late_trend=trend(
            key="late",
            title="Late arrivals",
            unit=Unit.COUNT,
            series_list=[series("late", "Late arrivals", months, late, missing=None)],
            definition="Attended shifts with a clock-in after the shift start, by month.",
            dataset="attendance",
        ),
        hours_trend=trend(
            key="hours",
            title="Scheduled and actual hours",
            unit=Unit.HOURS,
            series_list=[
                series("scheduled", "Scheduled hours", months, scheduled, missing=None),
                series("actual", "Actual hours", months, actual, missing=None),
            ],
            definition="Scheduled: the length of each counted rostered shift. Actual: clock-out "
            "minus clock-in on attended shifts (a shift without a clock-out adds none).",
            dataset="attendance",
        ),
        overtime_hours_trend=trend(
            key="overtime_hours",
            title="Overtime hours",
            unit=Unit.HOURS,
            series_list=[
                series(
                    "overtime",
                    "Overtime hours",
                    months,
                    _overtime_hours(db, org_id, filters, by_month=True),
                )
            ],
            definition="Approved or paid overtime hours by work date.",
        ),
        rate_by_department=breakdown(
            key="rate_by_department",
            title="Attendance rate by department",
            unit=Unit.PERCENT,
            rows=by_department,
            definition=rate_definition + " The count is rostered shifts.",
            dataset="attendance",
        ),
        rate_by_location=breakdown(
            key="rate_by_location",
            title="Attendance rate by location",
            unit=Unit.PERCENT,
            rows=by_location,
            definition=rate_definition + " The count is rostered shifts.",
            dataset="attendance",
        ),
        rate_by_weekday=breakdown(
            key="rate_by_weekday",
            title="Attendance rate by day of the week",
            unit=Unit.PERCENT,
            rows=by_weekday,
            definition=rate_definition + " The count is rostered shifts.",
            dataset="attendance",
            sort=False,
        ),
    )
