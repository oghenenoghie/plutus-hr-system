"""Drill-down: the source records behind an analytics figure, a page at a
time. Each dataset names the section permission it needs and the only
fields it returns, so a drill-down never exposes more than the dashboard's
own source module would (no pay on employee rows, no payslip lines without
payroll-register access, no ratings without review access)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, Time, and_, case, cast, func, literal, select
from sqlalchemy.orm import Session, aliased

from app.models.attendance_record import AttendanceRecord
from app.models.branch import Branch
from app.models.candidate import Candidate
from app.models.chart_account import ChartAccount
from app.models.department import Department
from app.models.employee import Employee
from app.models.job_posting import JobPosting
from app.models.journal_entry import JournalEntry
from app.models.leave import LeaveRequest
from app.models.ledger import LedgerEntry
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payslip_statutory_line import PayslipStatutoryLine
from app.models.performance_review import PerformanceReview
from app.models.shift import Shift
from app.models.shift_roster_entry import ShiftRosterEntry
from app.models.statutory_liability import LiabilityScheme, StatutoryLiability
from app.schemas.analytics import RecordColumn, RecordsPageOut, Section
from app.services.analytics.access import AccessDenied, AnalyticsAccess
from app.services.analytics.attendance import LOCAL_TZ
from app.services.analytics.common import departures_subquery, employed_on, employee_conditions
from app.services.analytics.compliance import SCHEME_CATEGORIES
from app.services.analytics.filters import AnalyticsFilters, FilterError

MAX_PAGE_SIZE = 100
MAX_EXPORT_ROWS = 20_000

Cell = str | int | float | None


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    section: Section
    columns: list[RecordColumn]
    query: Callable[[AnalyticsAccess, AnalyticsFilters], Select[Any]]
    individual: bool = False  # needs payroll-register (individual record) access


def _col(key: str, label: str, kind: str = "text") -> RecordColumn:
    return RecordColumn(key=key, label=label, kind=kind)


def _employee_columns() -> list[Any]:
    return [
        Employee.employee_number.label("employee_number"),
        Employee.full_name.label("employee"),
        Department.name.label("department"),
    ]


def _with_department(stmt: Select[Any]) -> Select[Any]:
    return stmt.outerjoin(Department, Employee.department_id == Department.id)


def _employees(kind: str) -> Callable[[AnalyticsAccess, AnalyticsFilters], Select[Any]]:
    def build(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
        departures = departures_subquery(access.org_id)
        stmt = (
            select(
                *_employee_columns(),
                Branch.name.label("location"),
                Employee.job_title.label("job_title"),
                Employee.employment_type.label("employment_type"),
                Employee.lifecycle_state.label("status"),
                Employee.date_of_joining.label("date_of_joining"),
                departures.c.left_on.label("left_on"),
            )
            .select_from(Employee)
            .outerjoin(departures, departures.c.employee_id == Employee.id)
            .outerjoin(Branch, Employee.branch_id == Branch.id)
            .where(Employee.org_id == access.org_id, *employee_conditions(filters))
            .order_by(Employee.full_name, Employee.employee_number)
        )
        stmt = _with_department(stmt)
        if kind == "hires":
            return stmt.where(Employee.date_of_joining.between(filters.date_from, filters.date_to))
        if kind == "departures":
            return stmt.where(departures.c.left_on.between(filters.date_from, filters.date_to))
        return stmt.where(
            employed_on(
                Employee.date_of_joining,
                Employee.lifecycle_state,
                departures.c.left_on,
                filters.date_to,
            )
        )

    return build


def _pay_runs(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    return (
        select(
            PayRun.period_start.label("period_start"),
            PayRun.period_end.label("period_end"),
            PayRun.run_type.label("run_type"),
            PayRun.status.label("status"),
            PayRun.employee_count.label("employees"),
            PayRun.gross_minor.label("gross"),
            PayRun.net_minor.label("net"),
        )
        .where(
            PayRun.org_id == access.org_id,
            PayRun.period_end.between(filters.date_from, filters.date_to),
        )
        .order_by(PayRun.period_end.desc(), PayRun.created_at.desc())
    )


def _payslips(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    stmt = (
        select(
            *_employee_columns(),
            PayRun.period_end.label("period_end"),
            PayRun.status.label("run_status"),
            Payslip.gross_minor.label("gross"),
            Payslip.pension_employer_minor.label("employer_pension"),
            Payslip.paye_minor.label("paye"),
            Payslip.pension_employee_minor.label("employee_pension"),
            Payslip.nhf_minor.label("nhf"),
            Payslip.net_minor.label("net"),
        )
        .select_from(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .join(Employee, Payslip.employee_id == Employee.id)
        .where(
            PayRun.org_id == access.org_id,
            PayRun.status.in_(filters.pay_run_statuses),
            PayRun.period_end.between(filters.date_from, filters.date_to),
            Payslip.rule_version_id.like(f"{filters.country}-%"),
            *employee_conditions(filters),
        )
        .order_by(PayRun.period_end.desc(), Employee.full_name)
    )
    return _with_department(stmt)


def _statutory_lines(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    """An engine country's payslips line by line (app/services/engine_payroll.py).
    Nigeria's figures are the payslip register's own columns, so it has none."""
    stmt = (
        select(
            *_employee_columns(),
            PayRun.period_end.label("period_end"),
            PayRun.status.label("run_status"),
            PayslipStatutoryLine.code.label("code"),
            PayslipStatutoryLine.name.label("name"),
            PayslipStatutoryLine.kind.label("kind"),
            PayslipStatutoryLine.authority.label("authority"),
            PayslipStatutoryLine.base_minor.label("base"),
            PayslipStatutoryLine.amount_minor.label("amount"),
            PayslipStatutoryLine.due_date.label("due_date"),
        )
        .select_from(PayslipStatutoryLine)
        .join(Payslip, PayslipStatutoryLine.payslip_id == Payslip.id)
        .join(PayRun, PayslipStatutoryLine.pay_run_id == PayRun.id)
        .join(Employee, Payslip.employee_id == Employee.id)
        .where(
            PayRun.org_id == access.org_id,
            PayRun.status.in_(filters.pay_run_statuses),
            PayRun.period_end.between(filters.date_from, filters.date_to),
            Payslip.rule_version_id.like(f"{filters.country}-%"),
            *employee_conditions(filters),
        )
        .order_by(PayRun.period_end.desc(), Employee.full_name, PayslipStatutoryLine.position)
    )
    return _with_department(stmt)


def _attendance(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    local_in = func.to_char(func.timezone(LOCAL_TZ, AttendanceRecord.clock_in_at), "HH24:MI")
    local_out = func.to_char(func.timezone(LOCAL_TZ, AttendanceRecord.clock_out_at), "HH24:MI")
    late = cast(func.timezone(LOCAL_TZ, AttendanceRecord.clock_in_at), Time) > Shift.start_time
    stmt = (
        select(
            *_employee_columns(),
            ShiftRosterEntry.work_date.label("work_date"),
            Shift.name.label("shift"),
            func.to_char(Shift.start_time, "HH24:MI").label("shift_start"),
            local_in.label("clock_in"),
            local_out.label("clock_out"),
            case(
                (AttendanceRecord.clock_in_at.is_(None), literal("No clock-in")),
                (late, literal("Late")),
                else_=literal("On time"),
            ).label("outcome"),
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
        .where(
            ShiftRosterEntry.org_id == access.org_id,
            ShiftRosterEntry.work_date.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
        .order_by(ShiftRosterEntry.work_date.desc(), Employee.full_name)
    )
    return _with_department(stmt)


def _leave_requests(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    stmt = (
        select(
            *_employee_columns(),
            LeaveRequest.leave_type.label("leave_type"),
            LeaveRequest.start_date.label("start_date"),
            LeaveRequest.end_date.label("end_date"),
            LeaveRequest.days.label("days"),
            LeaveRequest.status.label("status"),
        )
        .select_from(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .where(
            LeaveRequest.org_id == access.org_id,
            LeaveRequest.start_date.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
        .order_by(LeaveRequest.start_date.desc(), Employee.full_name)
    )
    return _with_department(stmt)


def _candidates(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    posting_department = aliased(Department)
    stmt = (
        select(
            Candidate.full_name.label("candidate"),
            JobPosting.title.label("posting"),
            posting_department.name.label("department"),
            Candidate.applied_date.label("applied_date"),
            Candidate.status.label("status"),
        )
        .select_from(Candidate)
        .join(JobPosting, Candidate.job_posting_id == JobPosting.id)
        .outerjoin(posting_department, JobPosting.department_id == posting_department.id)
        .where(
            Candidate.org_id == access.org_id,
            Candidate.applied_date.between(filters.date_from, filters.date_to),
        )
        .order_by(Candidate.applied_date.desc(), Candidate.full_name)
    )
    if filters.department_ids:
        stmt = stmt.where(JobPosting.department_id.in_(filters.department_ids))
    return stmt


def _reviews(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    rating = (
        PerformanceReview.rating
        if access.can_view_individual_pay
        else literal(None).label("rating")
    )
    stmt = (
        select(
            *_employee_columns(),
            PerformanceReview.period_start.label("period_start"),
            PerformanceReview.period_end.label("period_end"),
            PerformanceReview.status.label("status"),
            rating.label("rating"),
        )
        .select_from(PerformanceReview)
        .join(Employee, PerformanceReview.employee_id == Employee.id)
        .where(
            PerformanceReview.org_id == access.org_id,
            PerformanceReview.period_end.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
        .order_by(PerformanceReview.period_end.desc(), Employee.full_name)
    )
    return _with_department(stmt)


def _liabilities(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    return (
        select(
            StatutoryLiability.scheme.label("scheme"),
            StatutoryLiability.line_code.label("line_code"),
            StatutoryLiability.authority.label("authority"),
            StatutoryLiability.state.label("state"),
            StatutoryLiability.period_start.label("period_start"),
            StatutoryLiability.period_end.label("period_end"),
            StatutoryLiability.due_date.label("due_date"),
            StatutoryLiability.amount_minor.label("amount"),
            StatutoryLiability.status.label("status"),
        )
        .where(
            StatutoryLiability.org_id == access.org_id,
            StatutoryLiability.period_end.between(filters.date_from, filters.date_to),
        )
        .order_by(StatutoryLiability.due_date.desc(), StatutoryLiability.scheme)
    )


def _journal_lines(access: AnalyticsAccess, filters: AnalyticsFilters) -> Select[Any]:
    stmt = (
        select(
            JournalEntry.entry_date.label("entry_date"),
            JournalEntry.reference.label("reference"),
            JournalEntry.description.label("description"),
            LedgerEntry.account.label("account"),
            ChartAccount.name.label("account_name"),
            Department.name.label("department"),
            LedgerEntry.debit_minor.label("debit"),
            LedgerEntry.credit_minor.label("credit"),
        )
        .select_from(LedgerEntry)
        .join(JournalEntry, LedgerEntry.journal_entry_id == JournalEntry.id)
        .outerjoin(
            ChartAccount,
            and_(
                ChartAccount.org_id == LedgerEntry.org_id, ChartAccount.code == LedgerEntry.account
            ),
        )
        .outerjoin(Department, LedgerEntry.department_id == Department.id)
        .where(
            LedgerEntry.org_id == access.org_id,
            JournalEntry.entry_date.between(filters.date_from, filters.date_to),
            JournalEntry.currency == filters.currency,
        )
        .order_by(
            JournalEntry.entry_date.desc(), JournalEntry.created_at.desc(), LedgerEntry.account
        )
    )
    if filters.department_ids:
        stmt = stmt.where(LedgerEntry.department_id.in_(filters.department_ids))
    return stmt


_EMPLOYEE_COLUMNS = [
    _col("employee_number", "Employee no."),
    _col("employee", "Employee"),
    _col("department", "Department"),
]
_PEOPLE = [
    *_EMPLOYEE_COLUMNS,
    _col("location", "Location"),
    _col("job_title", "Job title"),
    _col("employment_type", "Employment type"),
    _col("status", "Status"),
    _col("date_of_joining", "Joined", "date"),
    _col("left_on", "Left", "date"),
]

DATASETS: dict[str, Dataset] = {
    d.key: d
    for d in (
        Dataset(
            "employees",
            "Employees in headcount",
            Section.WORKFORCE,
            _PEOPLE,
            _employees("headcount"),
        ),
        Dataset("hires", "New hires", Section.WORKFORCE, _PEOPLE, _employees("hires")),
        Dataset(
            "departures", "Employees who left", Section.WORKFORCE, _PEOPLE, _employees("departures")
        ),
        Dataset(
            "pay_runs",
            "Pay runs (organisation totals)",
            Section.PAYROLL,
            [
                _col("period_start", "Period start", "date"),
                _col("period_end", "Period end", "date"),
                _col("run_type", "Run type"),
                _col("status", "Status"),
                _col("employees", "Employees", "count"),
                _col("gross", "Gross pay", "money"),
                _col("net", "Net pay", "money"),
            ],
            _pay_runs,
        ),
        Dataset(
            "payslips",
            "Payslips",
            Section.PAYROLL,
            [
                *_EMPLOYEE_COLUMNS,
                _col("period_end", "Period end", "date"),
                _col("run_status", "Run status"),
                _col("gross", "Gross pay", "money"),
                _col("employer_pension", "Employer pension", "money"),
                _col("paye", "PAYE", "money"),
                _col("employee_pension", "Employee pension", "money"),
                _col("nhf", "NHF", "money"),
                _col("net", "Net pay", "money"),
            ],
            _payslips,
            individual=True,
        ),
        Dataset(
            "statutory_lines",
            "Payslip statutory lines",
            Section.PAYROLL,
            [
                *_EMPLOYEE_COLUMNS,
                _col("period_end", "Period end", "date"),
                _col("run_status", "Run status"),
                _col("code", "Code"),
                _col("name", "Line"),
                _col("kind", "Kind"),
                _col("authority", "Authority"),
                _col("base", "Base", "money"),
                _col("amount", "Amount", "money"),
                _col("due_date", "Due", "date"),
            ],
            _statutory_lines,
            individual=True,
        ),
        Dataset(
            "attendance",
            "Rostered shifts",
            Section.ATTENDANCE,
            [
                *_EMPLOYEE_COLUMNS,
                _col("work_date", "Date", "date"),
                _col("shift", "Shift"),
                _col("shift_start", "Starts"),
                _col("clock_in", "Clock-in (WAT)"),
                _col("clock_out", "Clock-out (WAT)"),
                _col("outcome", "Outcome"),
            ],
            _attendance,
        ),
        Dataset(
            "leave_requests",
            "Leave requests",
            Section.LEAVE,
            [
                *_EMPLOYEE_COLUMNS,
                _col("leave_type", "Type"),
                _col("start_date", "Starts", "date"),
                _col("end_date", "Ends", "date"),
                _col("days", "Days", "days"),
                _col("status", "Status"),
            ],
            _leave_requests,
        ),
        Dataset(
            "candidates",
            "Candidates",
            Section.RECRUITMENT,
            [
                _col("candidate", "Candidate"),
                _col("posting", "Job posting"),
                _col("department", "Department"),
                _col("applied_date", "Applied", "date"),
                _col("status", "Current stage"),
            ],
            _candidates,
        ),
        Dataset(
            "reviews",
            "Performance reviews",
            Section.PERFORMANCE,
            [
                *_EMPLOYEE_COLUMNS,
                _col("period_start", "Period start", "date"),
                _col("period_end", "Period end", "date"),
                _col("status", "Status"),
                _col("rating", "Rating", "count"),
            ],
            _reviews,
        ),
        Dataset(
            "liabilities",
            "Statutory liabilities",
            Section.COMPLIANCE,
            [
                _col("scheme", "Scheme"),
                _col("category", "Category"),
                _col("authority", "Authority"),
                _col("state", "State"),
                _col("period_start", "Period start", "date"),
                _col("period_end", "Period end", "date"),
                _col("due_date", "Due", "date"),
                _col("amount", "Amount", "money"),
                _col("status", "Status"),
            ],
            _liabilities,
        ),
        Dataset(
            "journal_lines",
            "Ledger lines",
            Section.FINANCIAL,
            [
                _col("entry_date", "Accounting date", "date"),
                _col("reference", "Reference"),
                _col("description", "Description"),
                _col("account", "Account"),
                _col("account_name", "Account name"),
                _col("department", "Department"),
                _col("debit", "Debit", "money"),
                _col("credit", "Credit", "money"),
            ],
            _journal_lines,
        ),
    )
}


def get_dataset(key: str, access: AnalyticsAccess) -> Dataset:
    dataset = DATASETS.get(key)
    if dataset is None:
        raise FilterError(f"unknown dataset: {key!r}")
    access.require(dataset.section)
    if dataset.individual and not access.can_view_individual_pay:
        raise AccessDenied("individual payslips need payroll-register access")
    return dataset


def _cell(value: object) -> Cell:
    if value is None or isinstance(value, str | int | float):
        return value
    if isinstance(value, date | datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # an enum
        return str(value.value)
    return str(value)


def _row(dataset: Dataset, mapping: Any) -> dict[str, Cell]:
    values = {key: _cell(value) for key, value in mapping.items()}
    if dataset.key == "liabilities":
        scheme = mapping["scheme"]
        line_code = values.pop("line_code")
        # A country's own obligation is named by its line codes.
        values["scheme"] = (
            line_code if scheme is LiabilityScheme.COUNTRY and line_code else scheme.value.upper()
        )
        values["category"] = SCHEME_CATEGORIES[scheme][1]
    return values


def page(
    db: Session,
    access: AnalyticsAccess,
    filters: AnalyticsFilters,
    dataset: Dataset,
    *,
    page_number: int,
    page_size: int,
) -> RecordsPageOut:
    if page_number < 1:
        raise FilterError("page must be at least 1")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise FilterError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    stmt = dataset.query(access, filters)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page_number - 1) * page_size)).mappings()
    return RecordsPageOut(
        dataset=dataset.key,
        title=dataset.title,
        currency=filters.currency,
        columns=dataset.columns,
        rows=[_row(dataset, r) for r in rows],
        page=page_number,
        page_size=page_size,
        total=total,
    )


def all_rows(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters, dataset: Dataset
) -> tuple[list[dict[str, Cell]], bool]:
    """Every row for an export, up to MAX_EXPORT_ROWS; the flag says the
    export was cut short."""
    stmt = dataset.query(access, filters).limit(MAX_EXPORT_ROWS + 1)
    rows = [_row(dataset, r) for r in db.execute(stmt).mappings()]
    return rows[:MAX_EXPORT_ROWS], len(rows) > MAX_EXPORT_ROWS
