"""Analytics & Insights API (docs/analytics-architecture.md).

Every endpoint resolves the caller's analytics access first, refuses a
section they lack (403), validates the filters on the server (422) and
narrows a department manager to the departments they head, then runs
read-only aggregate queries under row-level security. Responses are marked
private and uncacheable, and every export is written to the audit log.
"""

import enum
import uuid
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.compliance.multicountry import COUNTRY_PROFILES
from app.core.deps import get_current_claims, get_tenant_db
from app.core.security import TokenClaims
from app.models.branch import Branch
from app.models.department import Department
from app.models.employee import EmploymentType, LifecycleState
from app.models.organisation import Organisation
from app.schemas.analytics import (
    AccessOut,
    AttendanceOut,
    ComplianceOut,
    CountryOption,
    FilterOptionsOut,
    FinancialOut,
    LeaveOut,
    Option,
    OverviewOut,
    PayrollOut,
    PerformanceOut,
    RecordsPageOut,
    RecruitmentOut,
    Section,
    SectionAccess,
    WorkforceOut,
)
from app.services.analytics import (
    attendance,
    compliance,
    exports,
    financial,
    leave,
    overview,
    payroll,
    performance,
    records,
    recruitment,
    workforce,
)
from app.services.analytics.access import (
    AccessDenied,
    AnalyticsAccess,
    resolve_access,
    scoped_filters,
)
from app.services.analytics.common import build_meta, department_names, location_names
from app.services.analytics.filters import (
    MAX_RANGE_MONTHS,
    AnalyticsFilters,
    FilterError,
    default_range,
    parse_filters,
)
from app.services.audit import record_audit_event
from app.services.jurisdiction import organisation_country
from app.services.posting import today_lagos
from app.services.report_export import ReportTable, to_csv, to_pdf, to_xlsx


def _no_store(response: Response) -> None:
    # Analytics is confidential and per-tenant: never stored by a browser or
    # a shared cache. (An export sets the same header on its own Response.)
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(_no_store)])

STATEMENT_TIMEOUT = "15s"


class ExportFormat(enum.StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


_MEDIA_TYPES = {
    ExportFormat.CSV: "text/csv; charset=utf-8",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.PDF: "application/pdf",
}


class FilterQuery:
    """The filter bar's query string; validated by parse_filters."""

    def __init__(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        compare: str | None = None,
        department_id: Annotated[list[uuid.UUID] | None, Query()] = None,
        location_id: Annotated[list[uuid.UUID] | None, Query()] = None,
        employment_type: Annotated[list[str] | None, Query()] = None,
        status_: Annotated[list[str] | None, Query(alias="status")] = None,
        payroll_status: str | None = None,
        country: str | None = None,
    ) -> None:
        self.values: dict[str, Any] = {
            "date_from": date_from,
            "date_to": date_to,
            "compare": compare,
            "department_ids": department_id or [],
            "location_ids": location_id or [],
            "employment_types": employment_type or [],
            "statuses": status_ or [],
            "payroll_status": payroll_status,
            "country": country,
        }


def _access(db: Session, claims: TokenClaims) -> AnalyticsAccess:
    access = resolve_access(db, claims)
    if not access.can_view:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="requires permission: analytics.view"
        )
    return access


def _prepare(
    db: Session, claims: TokenClaims, query: FilterQuery, section: Section | None
) -> tuple[AnalyticsAccess, AnalyticsFilters]:
    access = _access(db, claims)
    try:
        if section is not None:
            access.require(section)
        filters = scoped_filters(
            db,
            access,
            parse_filters(
                today=today_lagos(),
                default_country=organisation_country(db, access.org_id),
                **query.values,
            ),
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FilterError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    # A guard against a pathological range or dataset tying up the database.
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    return access, filters


def _run[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except OperationalError as exc:
        if "statement timeout" in str(exc.orig):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="this report took too long; try a shorter date range or fewer filters",
            ) from exc
        raise


@router.get("/access", response_model=AccessOut)
def get_access(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(get_current_claims)
) -> AccessOut:
    """What the caller may see: drives the navigation and page guards. The
    endpoints check the same rules themselves."""
    access = resolve_access(db, claims)
    return AccessOut(
        can_view=access.can_view,
        sections=[SectionAccess(section=s, allowed=access.can(s)) for s in Section],
        can_export=access.can_export,
        can_view_individual_pay=access.can_view_individual_pay,
        department_scope=list(access.department_scope)
        if access.department_scope is not None
        else None,
    )


@router.get("/filter-options", response_model=FilterOptionsOut)
def get_filter_options(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(get_current_claims)
) -> FilterOptionsOut:
    access = _access(db, claims)
    departments = select(Department.id, Department.name).where(Department.org_id == access.org_id)
    if access.department_scope is not None:
        departments = departments.where(Department.id.in_(access.department_scope))
    default_from, default_to = default_range(today_lagos())
    return FilterOptionsOut(
        departments=[
            Option(value=str(i), label=name)
            for i, name in db.execute(departments.order_by(Department.name)).tuples()
        ],
        locations=[
            Option(value=str(i), label=name)
            for i, name in db.execute(
                select(Branch.id, Branch.name)
                .where(Branch.org_id == access.org_id)
                .order_by(Branch.name)
            ).tuples()
        ],
        employment_types=[
            Option(value=t.value, label=t.value.replace("_", " ").capitalize())
            for t in EmploymentType
        ],
        statuses=[Option(value=s.value, label=s.value.capitalize()) for s in LifecycleState],
        payroll_statuses=[
            Option(value="locked", label="Locked runs only"),
            Option(value="validated", label="Locked and validated runs"),
        ],
        countries=[
            CountryOption(code=p.code, name=p.name, currency=p.currency, status=p.status.value)
            for p in COUNTRY_PROFILES
        ],
        default_from=default_from,
        default_to=default_to,
        max_range_months=MAX_RANGE_MONTHS,
    )


@router.get("/overview", response_model=OverviewOut)
def get_overview(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> OverviewOut:
    access, filters = _prepare(db, claims, query, None)
    return _run(lambda: overview.overview(db, access, filters, today_lagos()))


@router.get("/workforce", response_model=WorkforceOut)
def get_workforce(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> WorkforceOut:
    access, filters = _prepare(db, claims, query, Section.WORKFORCE)
    return _run(lambda: workforce.workforce(db, access, filters))


@router.get("/payroll", response_model=PayrollOut)
def get_payroll(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> PayrollOut:
    access, filters = _prepare(db, claims, query, Section.PAYROLL)
    return _run(lambda: payroll.payroll(db, access, filters))


@router.get("/attendance", response_model=AttendanceOut)
def get_attendance(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> AttendanceOut:
    access, filters = _prepare(db, claims, query, Section.ATTENDANCE)
    return _run(lambda: attendance.attendance(db, access, filters))


@router.get("/leave", response_model=LeaveOut)
def get_leave(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> LeaveOut:
    access, filters = _prepare(db, claims, query, Section.LEAVE)
    return _run(lambda: leave.leave(db, access, filters))


@router.get("/recruitment", response_model=RecruitmentOut)
def get_recruitment(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> RecruitmentOut:
    access, filters = _prepare(db, claims, query, Section.RECRUITMENT)
    return _run(lambda: recruitment.recruitment(db, access, filters))


@router.get("/performance", response_model=PerformanceOut)
def get_performance(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> PerformanceOut:
    access, filters = _prepare(db, claims, query, Section.PERFORMANCE)
    return _run(lambda: performance.performance(db, access, filters))


@router.get("/compliance", response_model=ComplianceOut)
def get_compliance(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> ComplianceOut:
    access, filters = _prepare(db, claims, query, Section.COMPLIANCE)
    return _run(lambda: compliance.compliance(db, access, filters, today_lagos()))


@router.get("/financial", response_model=FinancialOut)
def get_financial(
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> FinancialOut:
    access, filters = _prepare(db, claims, query, Section.FINANCIAL)
    return _run(lambda: financial.financial(db, access, filters))


@router.get("/records/{dataset}", response_model=RecordsPageOut)
def get_records(
    dataset: str,
    page: int = 1,
    page_size: int = 25,
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> RecordsPageOut:
    """The source records behind a figure, a page at a time."""
    access, filters = _prepare(db, claims, query, None)
    try:
        definition = records.get_dataset(dataset, access)
        return _run(
            lambda: records.page(
                db, access, filters, definition, page_number=page, page_size=page_size
            )
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FilterError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


_SECTION_REPORTS: dict[str, tuple[Section | None, str, Callable[..., Any]]] = {
    "overview": (
        None,
        "Executive overview",
        lambda db, a, f: overview.overview(db, a, f, today_lagos()),
    ),
    "workforce": (Section.WORKFORCE, "Workforce analytics", workforce.workforce),
    "payroll": (Section.PAYROLL, "Payroll analytics", payroll.payroll),
    "attendance": (Section.ATTENDANCE, "Attendance analytics", attendance.attendance),
    "leave": (Section.LEAVE, "Leave analytics", leave.leave),
    "recruitment": (Section.RECRUITMENT, "Recruitment analytics", recruitment.recruitment),
    "performance": (Section.PERFORMANCE, "Performance analytics", performance.performance),
    "compliance": (
        Section.COMPLIANCE,
        "Tax and compliance analytics",
        lambda db, a, f: compliance.compliance(db, a, f, today_lagos()),
    ),
    "financial": (Section.FINANCIAL, "Financial analytics", financial.financial),
}


def _download(
    db: Session,
    claims: TokenClaims,
    table: ReportTable,
    fmt: ExportFormat,
    metadata: dict[str, Any],
) -> Response:
    organisation = db.get(Organisation, claims.org_id)
    if fmt == ExportFormat.CSV:
        content = to_csv(table)
    elif fmt == ExportFormat.XLSX:
        content = to_xlsx(table)
    else:
        content = to_pdf(table, organisation_name=organisation.name if organisation else "Plutus")
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="analytics.export",
        entity_type="analytics_report",
        metadata={**metadata, "format": fmt.value, "rows": len(table.rows)},
    )
    return Response(
        content=content,
        media_type=_MEDIA_TYPES[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{table.filename}.{fmt.value}"',
            "Cache-Control": "private, no-store",
        },
    )


def _metadata_lines(
    db: Session, access: AnalyticsAccess, claims: TokenClaims, meta: Any
) -> list[str]:
    organisation = db.get(Organisation, claims.org_id)
    return exports.metadata_lines(
        meta,
        organisation=organisation.name if organisation else "",
        department_names={str(k): v for k, v in department_names(db, access.org_id).items()},
        location_names={str(k): v for k, v in location_names(db, access.org_id).items()},
        role=claims.role,
    )


@router.get("/sections/{report}/export")
def export_section(
    report: str,
    format: ExportFormat = ExportFormat.CSV,
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Response:
    """A dashboard's KPIs, charts and definitions as CSV, XLSX or PDF."""
    if report not in _SECTION_REPORTS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown report")
    section, title, build = _SECTION_REPORTS[report]
    access, filters = _prepare(db, claims, query, section)
    try:
        access.require_export()
    except AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    result = _run(lambda: build(db, access, filters))
    table = exports.section_table(
        title,
        exports.export_filename(report, filters),
        result,
        _metadata_lines(db, access, claims, result.meta),
        filters.currency,
    )
    return _download(
        db,
        claims,
        table,
        format,
        {"report": report, "date_from": str(filters.date_from), "date_to": str(filters.date_to)},
    )


@router.get("/records/{dataset}/export")
def export_records(
    dataset: str,
    format: ExportFormat = ExportFormat.CSV,
    query: FilterQuery = Depends(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Response:
    """The source records behind a figure, every row (up to the export cap)."""
    access, filters = _prepare(db, claims, query, None)
    try:
        definition = records.get_dataset(dataset, access)
        access.require_export()
    except AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FilterError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    rows, truncated = _run(lambda: records.all_rows(db, access, filters, definition))
    meta = build_meta(definition.section.value, filters, access)
    table = exports.records_table(
        definition.title,
        exports.export_filename(dataset, filters),
        definition.columns,
        rows,
        _metadata_lines(db, access, claims, meta),
        truncated=truncated,
        limit=records.MAX_EXPORT_ROWS,
        currency=meta.currency,
    )
    return _download(
        db,
        claims,
        table,
        format,
        {
            "dataset": dataset,
            "date_from": str(filters.date_from),
            "date_to": str(filters.date_to),
            "truncated": truncated,
        },
    )
