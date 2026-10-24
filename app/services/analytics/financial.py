"""Financial analytics from the general ledger.

Lines are dated by their journal's entry_date, the accounting date, and
limited to journals in the selected country's currency, so no figure adds
two currencies. Revenue reads credit minus debit and expenses debit minus
credit, as in the income statement. The existing statements still date
lines by when they were posted (docs/analytics-architecture.md, A7), so a
backdated journal lands in a different month there. Definitions:
docs/analytics-metrics.md §8.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.orm import Session

from app.models.budget import Budget, BudgetLine
from app.models.chart_account import AccountType, ChartAccount
from app.models.company_bank_account import CompanyBankAccount
from app.models.journal_entry import JournalEntry
from app.models.ledger import LedgerEntry
from app.schemas.analytics import BudgetActualRow, FinancialOut, Metric, Unit
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import (
    NO_DEPARTMENT,
    breakdown,
    build_meta,
    department_names,
    metric,
    percent,
    row,
    series,
    top_rows,
    trend,
)
from app.services.analytics.filters import AnalyticsFilters, month_keys

HREF = "/analytics/financial"

# The expense accounts payroll and its employer-side accruals post to
# (services/chart_accounts.DEFAULT_ACCOUNTS).
PAYROLL_EXPENSE_ACCOUNTS = (
    "payroll_expense_gross",
    "payroll_expense_employer_pension",
    "payroll_expense_nsitf",
)
CASH_ACCOUNT = "cash"

_REVENUE = ChartAccount.type == AccountType.REVENUE
_EXPENSE = ChartAccount.type == AccountType.EXPENSE
_REVENUE_AMOUNT = LedgerEntry.credit_minor - LedgerEntry.debit_minor
_EXPENSE_AMOUNT = LedgerEntry.debit_minor - LedgerEntry.credit_minor


def _lines(filters: AnalyticsFilters, org_id: uuid.UUID, *columns: Any) -> Any:
    conditions: list[ColumnElement[bool]] = [
        LedgerEntry.org_id == org_id,
        JournalEntry.entry_date.between(filters.date_from, filters.date_to),
        JournalEntry.currency == filters.currency,
    ]
    if filters.department_ids:
        conditions.append(LedgerEntry.department_id.in_(filters.department_ids))
    return (
        select(*columns)
        .select_from(LedgerEntry)
        .join(JournalEntry, LedgerEntry.journal_entry_id == JournalEntry.id)
        .join(
            ChartAccount,
            and_(
                ChartAccount.org_id == LedgerEntry.org_id, ChartAccount.code == LedgerEntry.account
            ),
        )
        .where(*conditions)
    )


def _cash_accounts(db: Session, org_id: uuid.UUID) -> list[str]:
    bank_codes = db.scalars(
        select(CompanyBankAccount.chart_account_code).where(CompanyBankAccount.org_id == org_id)
    )
    return sorted({CASH_ACCOUNT, *bank_codes})


def _sum(expression: Any, condition: ColumnElement[bool]) -> Any:
    return func.coalesce(func.sum(expression).filter(condition), 0)


def _figure_columns(cash_accounts: list[str]) -> list[Any]:
    return [
        _sum(_REVENUE_AMOUNT, _REVENUE).label("revenue"),
        _sum(_EXPENSE_AMOUNT, _EXPENSE).label("expenses"),
        _sum(_EXPENSE_AMOUNT, _EXPENSE & LedgerEntry.account.in_(PAYROLL_EXPENSE_ACCOUNTS)).label(
            "payroll"
        ),
        _sum(_EXPENSE_AMOUNT, LedgerEntry.account.in_(cash_accounts)).label("cash"),
        func.count(LedgerEntry.id).label("lines"),
    ]


def _derive(values: dict[str, int]) -> dict[str, float | int | None]:
    if not values.pop("lines"):
        # Nothing posted in the period: no figures, rather than ₦0 (which
        # would also make every comparison a rise "from ₦0").
        return dict.fromkeys(
            ("revenue", "expenses", "payroll", "cash", "net_income", "payroll_share")
        )
    return {
        **values,
        "net_income": values["revenue"] - values["expenses"],
        "payroll_share": percent(values["payroll"], values["expenses"]),
    }


def _period(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters, cash: list[str]
) -> dict[str, Any]:
    result = db.execute(_lines(filters, org_id, *_figure_columns(cash))).mappings().one()
    return _derive({key: int(value) for key, value in result.items()})


def budget_vs_actual(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters
) -> list[BudgetActualRow]:
    """Each budget overlapping the period against ledger activity on its
    accounts within the budget's own dates, as the budgets screen compares
    them (no department narrowing of the actuals), but by accounting date."""
    overlapping = [
        Budget.org_id == org_id,
        Budget.period_start <= filters.date_to,
        Budget.period_end >= filters.date_from,
    ]
    if filters.department_ids:
        overlapping.append(Budget.department_id.in_(filters.department_ids))
    budgets = list(
        db.scalars(
            select(Budget).where(*overlapping).order_by(Budget.period_start, Budget.name).limit(20)
        )
    )
    if not budgets:
        return []
    ids = [b.id for b in budgets]
    budgeted = {
        budget_id: int(amount)
        for budget_id, amount in db.execute(
            select(BudgetLine.budget_id, func.sum(BudgetLine.amount_minor))
            .where(BudgetLine.budget_id.in_(ids))
            .group_by(BudgetLine.budget_id)
        ).tuples()
    }
    signed = case((_REVENUE, _REVENUE_AMOUNT), else_=_EXPENSE_AMOUNT)
    actual = {
        budget_id: int(amount)
        for budget_id, amount in db.execute(
            select(BudgetLine.budget_id, func.coalesce(func.sum(signed), 0))
            .select_from(BudgetLine)
            .join(Budget, BudgetLine.budget_id == Budget.id)
            .join(
                ChartAccount,
                and_(
                    ChartAccount.org_id == Budget.org_id,
                    ChartAccount.code == BudgetLine.account_code,
                ),
            )
            .join(
                LedgerEntry,
                and_(
                    LedgerEntry.org_id == Budget.org_id,
                    LedgerEntry.account == BudgetLine.account_code,
                ),
            )
            .join(
                JournalEntry,
                and_(
                    JournalEntry.id == LedgerEntry.journal_entry_id,
                    JournalEntry.entry_date.between(Budget.period_start, Budget.period_end),
                    JournalEntry.currency == filters.currency,
                ),
            )
            .where(BudgetLine.budget_id.in_(ids))
            .group_by(BudgetLine.budget_id)
        ).tuples()
    }
    names = department_names(db, org_id)
    return [
        BudgetActualRow(
            budget_id=b.id,
            name=b.name,
            department_name=names.get(b.department_id) if b.department_id else None,
            period_start=b.period_start,
            period_end=b.period_end,
            budgeted_minor=budgeted.get(b.id, 0),
            actual_minor=actual.get(b.id, 0),
            variance_minor=actual.get(b.id, 0) - budgeted.get(b.id, 0),
        )
        for b in budgets
    ]


def unclassified_lines(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> int:
    """Ledger lines in the period on an account code missing from the chart
    of accounts (it is seeded on request, not at sign-up). Like the income
    statement, analytics can't classify them, so it says how many it left out."""
    return (
        db.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .join(JournalEntry, LedgerEntry.journal_entry_id == JournalEntry.id)
            .outerjoin(
                ChartAccount,
                and_(
                    ChartAccount.org_id == LedgerEntry.org_id,
                    ChartAccount.code == LedgerEntry.account,
                ),
            )
            .where(
                LedgerEntry.org_id == org_id,
                JournalEntry.entry_date.between(filters.date_from, filters.date_to),
                JournalEntry.currency == filters.currency,
                ChartAccount.id.is_(None),
            )
        )
        or 0
    )


def financial(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> FinancialOut:
    org_id = access.org_id
    currency = filters.currency
    months = month_keys(filters.date_from, filters.date_to)
    cash = _cash_accounts(db, org_id)
    now = _period(db, org_id, filters, cash)
    previous_filters = filters.comparison()
    before = _period(db, org_id, previous_filters, cash) if previous_filters else {}
    compare = previous_filters is not None

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
            dataset="journal_lines",
        )

    kpis = [
        money("revenue", "Revenue", "Credits minus debits on revenue accounts.", better=True),
        money(
            "expenses",
            "Expenses",
            "Debits minus credits on every expense account. The chart of accounts doesn't "
            "separate operating from other expenses, so this is all of them.",
            better=False,
        ),
        money(
            "payroll",
            "Payroll expense",
            "Expense posted to the payroll accounts (gross pay, employer pension, NSITF) when pay "
            "runs lock. An accrual, not the net pay employees received.",
        ),
        metric(
            key="payroll_share",
            label="Payroll share of expenses",
            unit=Unit.PERCENT,
            value=now["payroll_share"],
            previous=before.get("payroll_share"),
            compare=compare,
            definition="Payroll expense ÷ all expenses × 100.",
            href=HREF,
        ),
        money("net_income", "Net income", "Revenue minus expenses.", better=True),
        money(
            "cash",
            "Net cash movement",
            "Debits minus credits on the cash account and every account linked to a company "
            "bank account: money in less money out.",
            better=True,
        ),
    ]

    month = func.to_char(JournalEntry.entry_date, "YYYY-MM").label("month")
    monthly = {
        r["month"]: _derive({k: int(v) for k, v in r.items() if k != "month"})
        for r in db.execute(
            _lines(filters, org_id, month, *_figure_columns(cash)).group_by(month)
        ).mappings()
    }

    def values(key: str) -> dict[str, float | int | None]:
        return {m: figures[key] for m, figures in monthly.items()}

    names = department_names(db, org_id)
    by_department = [
        row(
            dept or "none",
            names.get(dept, NO_DEPARTMENT) if dept else "Not assigned to a department",
            int(amount),
        )
        for dept, amount in db.execute(
            _lines(filters, org_id, LedgerEntry.department_id, func.sum(_EXPENSE_AMOUNT))
            .where(_EXPENSE)
            .group_by(LedgerEntry.department_id)
        ).tuples()
    ]
    by_account = top_rows(
        [
            row(code, name, int(amount))
            for code, name, amount in db.execute(
                _lines(
                    filters, org_id, ChartAccount.code, ChartAccount.name, func.sum(_EXPENSE_AMOUNT)
                )
                .where(_EXPENSE)
                .group_by(ChartAccount.code, ChartAccount.name)
            ).tuples()
        ],
        8,
        "Other expense accounts",
    )

    unclassified = unclassified_lines(db, org_id, filters)
    unclassified_note = (
        [
            (
                f"{unclassified} ledger line(s) in the period post to accounts that aren't in "
                "the chart of accounts, so they are left out, as in the income statement. "
                "Seed the chart of accounts to include them."
            )
        ]
        if unclassified
        else []
    )

    return FinancialOut(
        meta=build_meta(
            "financial",
            filters,
            access,
            notes=[
                (
                    "Dated by each journal's accounting date (entry date). The income statement "
                    "and budget screens date by posting time, so a backdated journal can fall in "
                    "a different month there."
                ),
                f"Only journals in {currency}.",
                *unclassified_note,
                (
                    "The department filter keeps ledger lines tagged with those departments; most "
                    "revenue lines carry no department."
                ),
            ],
        ),
        kpis=kpis,
        revenue_expense_trend=trend(
            key="revenue_expenses",
            title="Revenue and expenses",
            unit=Unit.MONEY,
            currency=currency,
            series_list=[
                series("revenue", "Revenue", months, values("revenue")),
                series("expenses", "Expenses", months, values("expenses")),
            ],
            definition="Revenue and total expenses by the accounting month. Two measures, so "
            "not stacked.",
            dataset="journal_lines",
        ),
        payroll_share_trend=trend(
            key="payroll_share",
            title="Payroll share of expenses",
            unit=Unit.PERCENT,
            series_list=[
                series(
                    "payroll_share", "Payroll share", months, values("payroll_share"), missing=None
                )
            ],
            definition="Payroll expense ÷ all expenses × 100, by accounting month; no value for a "
            "month without expenses.",
        ),
        cash_movement_trend=trend(
            key="cash",
            title="Net cash movement",
            unit=Unit.MONEY,
            currency=currency,
            series_list=[series("cash", "Net cash movement", months, values("cash"))],
            definition="Debits minus credits on cash and bank accounts, by accounting month.",
            dataset="journal_lines",
        ),
        expenses_by_department=breakdown(
            key="expenses_by_department",
            title="Expenses by department",
            unit=Unit.MONEY,
            currency=currency,
            rows=by_department,
            definition="Expense lines by the department they were tagged with when posted.",
            dataset="journal_lines",
        ),
        expenses_by_account=breakdown(
            key="expenses_by_account",
            title="Expenses by account",
            unit=Unit.MONEY,
            currency=currency,
            rows=by_account,
            definition="Expense by account; the seven largest, the rest together.",
            dataset="journal_lines",
            sort=False,
        ),
        budget_vs_actual=budget_vs_actual(db, org_id, filters),
    )
