"""Tax and compliance analytics, read from the statutory liabilities the
payroll and contractor flows already raise (with due dates from the rule
version) and from input VAT recorded on bills. Nothing here recalculates a
tax: the liabilities are the record. Each scheme is kept in its own
category, and VAT is reported apart from every payroll obligation.
Definitions: docs/analytics-metrics.md §7.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance.multicountry import get_country_profile
from app.models.bill import Bill, BillStatus
from app.models.statutory_liability import LiabilityScheme, LiabilityStatus, StatutoryLiability
from app.schemas.analytics import ComplianceOut, DeadlineOut, Metric, Unit
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import breakdown, build_meta, metric, row, series, trend
from app.services.analytics.filters import AnalyticsFilters, month_keys

HREF = "/analytics/compliance"
DEADLINE_WINDOW_DAYS = 30

# (category key, category label). PAYE is the payroll tax; NHF and the
# employee half of pension are employee statutory deductions; NSITF and ITF
# are employer contributions; WHT is withheld from suppliers, not payroll.
SCHEME_CATEGORIES: dict[LiabilityScheme, tuple[str, str]] = {
    LiabilityScheme.PAYE: ("payroll_tax", "Payroll tax (PAYE)"),
    LiabilityScheme.PENSION: ("pension", "Pension (employee and employer)"),
    LiabilityScheme.NHF: ("employee_contributions", "Employee contributions (NHF)"),
    LiabilityScheme.NSITF: ("employer_contributions", "Employer contributions (NSITF, ITF)"),
    LiabilityScheme.ITF: ("employer_contributions", "Employer contributions (NSITF, ITF)"),
    LiabilityScheme.WHT: ("withholding_tax", "Withholding tax"),
}
_SCHEME_LABELS = {
    LiabilityScheme.PAYE: "PAYE",
    LiabilityScheme.PENSION: "Pension",
    LiabilityScheme.NHF: "NHF",
    LiabilityScheme.NSITF: "NSITF",
    LiabilityScheme.ITF: "ITF",
    LiabilityScheme.WHT: "WHT",
}
_STATUS_LABELS = {
    LiabilityStatus.PENDING: "Pending",
    LiabilityStatus.FILED: "Filed",
    LiabilityStatus.REMITTED: "Remitted",
}


def _in_period(filters: AnalyticsFilters, org_id: uuid.UUID, *columns: Any) -> Any:
    return select(*columns).where(
        StatutoryLiability.org_id == org_id,
        StatutoryLiability.period_end.between(filters.date_from, filters.date_to),
    )


def _period(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, int | None]:
    remitted = StatutoryLiability.status == LiabilityStatus.REMITTED
    totals = (
        db.execute(
            _in_period(
                filters,
                org_id,
                func.coalesce(func.sum(StatutoryLiability.amount_minor), 0).label("total"),
                func.coalesce(
                    func.sum(StatutoryLiability.amount_minor).filter(
                        StatutoryLiability.scheme == LiabilityScheme.PAYE
                    ),
                    0,
                ).label("paye"),
                func.coalesce(
                    func.sum(StatutoryLiability.amount_minor).filter(
                        StatutoryLiability.scheme.in_((LiabilityScheme.NSITF, LiabilityScheme.ITF))
                    ),
                    0,
                ).label("employer"),
                func.count().label("liabilities"),
            )
        )
        .mappings()
        .one()
    )
    due = (
        db.execute(
            select(
                func.count().filter(remitted).label("completed"),
                func.count().filter(~remitted).label("outstanding"),
            ).where(
                StatutoryLiability.org_id == org_id,
                StatutoryLiability.due_date.between(filters.date_from, filters.date_to),
            )
        )
        .mappings()
        .one()
    )
    amounts: dict[str, int | None] = {k: int(v) for k, v in totals.items()}
    if not amounts.pop("liabilities"):
        # No liability raised for the period: no figure, rather than a ₦0
        # that would read as "nothing owed" (or a rise from ₦0).
        amounts = dict.fromkeys(amounts)
    return {**amounts, **{k: int(v) for k, v in due.items()}}


def deadlines(db: Session, org_id: uuid.UUID, today: date, *, limit: int = 50) -> list[DeadlineOut]:
    """Every obligation not yet remitted that is overdue or due within the
    next 30 days, earliest first."""
    rows = db.scalars(
        select(StatutoryLiability)
        .where(
            StatutoryLiability.org_id == org_id,
            StatutoryLiability.status != LiabilityStatus.REMITTED,
            StatutoryLiability.due_date <= today + timedelta(days=DEADLINE_WINDOW_DAYS),
        )
        .order_by(StatutoryLiability.due_date, StatutoryLiability.scheme)
        .limit(limit)
    )
    return [
        DeadlineOut(
            id=liability.id,
            scheme=_SCHEME_LABELS[liability.scheme],
            category=SCHEME_CATEGORIES[liability.scheme][1],
            authority=liability.authority,
            period_start=liability.period_start,
            period_end=liability.period_end,
            due_date=liability.due_date,
            amount_minor=liability.amount_minor,
            status=liability.status.value,
            overdue=liability.due_date < today,
        )
        for liability in rows
    ]


def _outstanding(db: Session, org_id: uuid.UUID, today: date) -> dict[str, int]:
    open_ = StatutoryLiability.status != LiabilityStatus.REMITTED
    overdue = open_ & (StatutoryLiability.due_date < today)
    upcoming = (
        open_
        & (StatutoryLiability.due_date >= today)
        & (StatutoryLiability.due_date <= today + timedelta(days=DEADLINE_WINDOW_DAYS))
    )
    result = (
        db.execute(
            select(
                func.coalesce(func.sum(StatutoryLiability.amount_minor).filter(open_), 0).label(
                    "outstanding_amount"
                ),
                func.count().filter(overdue).label("overdue_count"),
                func.coalesce(func.sum(StatutoryLiability.amount_minor).filter(overdue), 0).label(
                    "overdue_amount"
                ),
                func.count().filter(upcoming).label("upcoming_count"),
                func.coalesce(func.sum(StatutoryLiability.amount_minor).filter(upcoming), 0).label(
                    "upcoming_amount"
                ),
            ).where(StatutoryLiability.org_id == org_id)
        )
        .mappings()
        .one()
    )
    return {key: int(value) for key, value in result.items()}


def compliance_kpis(
    db: Session,
    access: AnalyticsAccess,
    filters: AnalyticsFilters,
    today: date,
    *,
    overview: bool = False,
) -> list[Metric]:
    org_id = access.org_id
    currency = filters.currency
    open_now = _outstanding(db, org_id, today)
    overdue = metric(
        key="overdue",
        label="Overdue obligations",
        unit=Unit.COUNT,
        value=open_now["overdue_count"],
        compare=False,
        higher_is_better=False,
        definition="Statutory liabilities past their due date and not yet remitted, today.",
        href=HREF,
        dataset="liabilities",
        note=None,
    )
    upcoming = metric(
        key="upcoming",
        label=f"Due in the next {DEADLINE_WINDOW_DAYS} days",
        unit=Unit.MONEY,
        value=open_now["upcoming_amount"],
        compare=False,
        currency=currency,
        definition=f"Unremitted liabilities due in the next {DEADLINE_WINDOW_DAYS} days; the "
        "due dates come from the rule version that raised each one.",
        href=HREF,
        dataset="liabilities",
        note=f"{open_now['upcoming_count']} obligation(s)",
    )
    if overview:
        return [overdue, upcoming]
    now = _period(db, org_id, filters)
    previous_filters = filters.comparison()
    before = _period(db, org_id, previous_filters) if previous_filters else {}
    compare = previous_filters is not None

    def money(key: str, label: str, definition: str) -> Metric:
        return metric(
            key=key,
            label=label,
            unit=Unit.MONEY,
            value=now[key],
            previous=before.get(key),
            compare=compare,
            currency=currency,
            definition=definition,
            href=HREF,
            dataset="liabilities",
        )

    return [
        money(
            "paye",
            "PAYE liability",
            "PAYE liabilities for periods ending in the range, as raised at pay-run lock.",
        ),
        money(
            "employer",
            "Employer contributions",
            "NSITF and ITF liabilities for periods ending in the range. Employer pension is "
            "inside the pension liability.",
        ),
        money(
            "total",
            "All statutory obligations",
            "Every statutory liability (PAYE, pension, NHF, NSITF, ITF, WHT) for periods ending "
            "in the range. VAT is not included.",
        ),
        metric(
            key="outstanding",
            label="Outstanding today",
            unit=Unit.MONEY,
            value=open_now["outstanding_amount"],
            compare=False,
            currency=currency,
            higher_is_better=False,
            definition="Every liability not yet remitted, whatever its period.",
            href=HREF,
            dataset="liabilities",
        ),
        overdue,
        upcoming,
        metric(
            key="completed",
            label="Obligations completed",
            unit=Unit.COUNT,
            value=now["completed"],
            previous=before.get("completed"),
            compare=compare,
            higher_is_better=True,
            definition="Liabilities due in the period that have been remitted.",
            href=HREF,
            dataset="liabilities",
            note=f"{now['outstanding']} due in the period still outstanding",
        ),
    ]


def compliance(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters, today: date
) -> ComplianceOut:
    org_id = access.org_id
    currency = filters.currency
    months = month_keys(filters.date_from, filters.date_to)
    month = func.to_char(StatutoryLiability.period_end, "YYYY-MM")

    monthly: dict[LiabilityScheme, dict[str, int]] = {}
    for scheme, key, amount in db.execute(
        _in_period(
            filters,
            org_id,
            StatutoryLiability.scheme,
            month,
            func.sum(StatutoryLiability.amount_minor),
        ).group_by(StatutoryLiability.scheme, month)
    ).tuples():
        monthly.setdefault(scheme, {})[key] = int(amount)

    categories: dict[str, list[Any]] = {}
    for scheme, amount, count in db.execute(
        _in_period(
            filters,
            org_id,
            StatutoryLiability.scheme,
            func.sum(StatutoryLiability.amount_minor),
            func.count(),
        ).group_by(StatutoryLiability.scheme)
    ).tuples():
        key, label = SCHEME_CATEGORIES[scheme]
        entry = categories.setdefault(key, [label, 0, 0])
        entry[1] += int(amount)
        entry[2] += count

    statuses = [
        row(status.value, _STATUS_LABELS[status], int(amount), count=count)
        for status, amount, count in db.execute(
            _in_period(
                filters,
                org_id,
                StatutoryLiability.status,
                func.sum(StatutoryLiability.amount_minor),
                func.count(),
            ).group_by(StatutoryLiability.status)
        ).tuples()
    ]

    vat_month = func.to_char(Bill.bill_date, "YYYY-MM")
    vat = {
        key: int(amount)
        for key, amount in db.execute(
            select(vat_month, func.coalesce(func.sum(Bill.vat_minor), 0))
            .where(
                Bill.org_id == org_id,
                Bill.status.in_((BillStatus.APPROVED, BillStatus.PAID)),
                Bill.bill_date.between(filters.date_from, filters.date_to),
            )
            .group_by(vat_month)
        ).tuples()
    }

    return ComplianceOut(
        meta=build_meta(
            "compliance",
            filters,
            access,
            notes=[
                (
                    "Statutory obligations are organisation-wide, so the department, location, "
                    "employment-type and status filters don't apply here."
                ),
                (
                    "Liabilities count in the month their period ends; deadlines use the due "
                    "dates the rule version set when each liability was raised."
                ),
                (
                    "VAT is reported separately and is not a payroll tax. Only input VAT on "
                    "approved and paid bills is recorded; output VAT on sales isn't tracked."
                ),
            ],
        ),
        country_name=get_country_profile(filters.country).name,
        kpis=compliance_kpis(db, access, filters, today),
        obligations_trend=trend(
            key="obligations",
            title="Statutory obligations by scheme",
            unit=Unit.MONEY,
            currency=currency,
            stacked=True,
            series_list=[
                series(scheme.value, _SCHEME_LABELS[scheme], months, monthly[scheme])
                for scheme in LiabilityScheme
                if scheme in monthly
            ],
            definition="Liability amounts by the month their period ends, stacked by scheme.",
            dataset="liabilities",
        ),
        obligations_by_category=breakdown(
            key="by_category",
            title="Obligations by category",
            unit=Unit.MONEY,
            currency=currency,
            rows=[
                row(key, label, amount, count=count)
                for key, (label, amount, count) in categories.items()
            ],
            definition="Liabilities for periods ending in the range, grouped into payroll tax, "
            "pension, employee and employer contributions and withholding tax; the count is "
            "liabilities.",
            dataset="liabilities",
        ),
        obligations_by_status=breakdown(
            key="by_status",
            title="Obligations by status",
            unit=Unit.MONEY,
            currency=currency,
            rows=statuses,
            definition="Liabilities for periods ending in the range, by filing status.",
            dataset="liabilities",
        ),
        input_vat_trend=trend(
            key="input_vat",
            title="Input VAT on bills",
            unit=Unit.MONEY,
            currency=currency,
            series_list=[series("input_vat", "Input VAT", months, vat)],
            definition="VAT on approved and paid supplier bills, by bill date. Recoverable, and "
            "not a payroll obligation.",
        ),
        deadlines=deadlines(db, org_id, today),
    )
