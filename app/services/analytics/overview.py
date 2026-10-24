"""The executive overview: the headline KPIs and charts from each section
the caller may see. A section they can't see contributes nothing; it isn't
shown as zero. Every figure comes from the section's own function, so the
overview always agrees with the section page."""

from datetime import date

from sqlalchemy.orm import Session

from app.schemas.analytics import Metric, OverviewOut, Section
from app.services.analytics import attendance, compliance, leave, payroll, workforce
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import build_meta
from app.services.analytics.filters import AnalyticsFilters

_WORKFORCE_KPIS = ("headcount", "active", "hires", "departures", "turnover")


def overview(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters, today: date
) -> OverviewOut:
    kpis: list[Metric] = []
    trailing: list[Metric] = []
    headcount_trend = payroll_cost_trend = headcount_by_department = None
    deadlines = None

    if access.can(Section.WORKFORCE):
        by_key = {m.key: m for m in workforce.workforce_kpis(db, access, filters)}
        kpis += [by_key[key] for key in _WORKFORCE_KPIS]
        headcount_trend = workforce.headcount_trend(db, access, filters)
        headcount_by_department = workforce.headcount_by_department(db, access, filters)
    if access.can(Section.PAYROLL):
        cost, average_gross, status = payroll.payroll_kpis(db, access, filters, overview=True)
        kpis += [cost, average_gross]
        trailing.append(status)
        payroll_cost_trend = payroll.cost_trend(db, access, filters)
    if access.can(Section.ATTENDANCE):
        kpis += attendance.attendance_kpis(db, access, filters, overview=True)
    if access.can(Section.LEAVE):
        kpis += leave.leave_kpis(db, access, filters, overview=True)
    kpis += trailing
    if access.can(Section.COMPLIANCE):
        kpis += compliance.compliance_kpis(db, access, filters, today, overview=True)
        deadlines = compliance.deadlines(db, access.org_id, today, limit=8)

    return OverviewOut(
        meta=build_meta(
            "overview",
            filters,
            access,
            notes=[
                "Each figure links to its section, where the definitions and source records are."
            ],
        ),
        kpis=kpis,
        headcount_trend=headcount_trend,
        payroll_cost_trend=payroll_cost_trend,
        headcount_by_department=headcount_by_department,
        deadlines=deadlines,
        restricted_sections=[section for section in Section if not access.can(section)],
    )
