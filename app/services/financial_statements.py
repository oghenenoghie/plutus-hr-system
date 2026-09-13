import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chart_account import AccountType, ChartAccount
from app.models.ledger import LedgerEntry
from app.schemas.financial_statements import BalanceSheetOut, IncomeStatementOut, StatementLine


def _accounts_by_code(
    db: Session, *, org_id: uuid.UUID, types: tuple[AccountType, ...]
) -> dict[str, ChartAccount]:
    accounts = db.scalars(
        select(ChartAccount).where(ChartAccount.org_id == org_id, ChartAccount.type.in_(types))
    )
    return {account.code: account for account in accounts}


def _debit_credit_totals(
    db: Session, *, accounts: dict[str, ChartAccount], from_date: date | None, to_date: date | None
) -> dict[str, tuple[int, int]]:
    stmt = select(LedgerEntry)
    if from_date is not None:
        stmt = stmt.where(LedgerEntry.created_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(LedgerEntry.created_at < to_date + timedelta(days=1))

    totals: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for entry in db.scalars(stmt):
        if entry.account not in accounts:
            continue
        debit, credit = totals[entry.account]
        totals[entry.account] = (debit + entry.debit_minor, credit + entry.credit_minor)
    return totals


def balance_sheet(db: Session, *, org_id: uuid.UUID, as_of: date | None = None) -> BalanceSheetOut:
    """A point-in-time snapshot (all activity up to `as_of`, or all time if
    omitted) of asset/liability/equity accounts. The only seeded equity
    account is revaluation_surplus (see revalue_fixed_asset), and this
    build has no period-end closing process, so a healthy org's assets
    will not yet equal liabilities + equity — a disclosed simplification,
    not a bug in this aggregation.
    """
    accounts = _accounts_by_code(
        db, org_id=org_id, types=(AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY)
    )
    totals = _debit_credit_totals(db, accounts=accounts, from_date=None, to_date=as_of)

    assets, liabilities, equity = [], [], []
    total_assets = total_liabilities = total_equity = 0
    for code, account in sorted(accounts.items()):
        debit, credit = totals.get(code, (0, 0))
        if account.type == AccountType.ASSET:
            balance = debit - credit
            assets.append(
                StatementLine(account=code, account_name=account.name, balance_minor=balance)
            )
            total_assets += balance
        elif account.type == AccountType.LIABILITY:
            balance = credit - debit
            liabilities.append(
                StatementLine(account=code, account_name=account.name, balance_minor=balance)
            )
            total_liabilities += balance
        else:
            balance = credit - debit
            equity.append(
                StatementLine(account=code, account_name=account.name, balance_minor=balance)
            )
            total_equity += balance

    return BalanceSheetOut(
        as_of=as_of,
        assets=assets,
        total_assets_minor=total_assets,
        liabilities=liabilities,
        total_liabilities_minor=total_liabilities,
        equity=equity,
        total_equity_minor=total_equity,
    )


def income_statement(
    db: Session, *, org_id: uuid.UUID, from_date: date | None = None, to_date: date | None = None
) -> IncomeStatementOut:
    """A period aggregation (all time if both dates are omitted) of
    revenue/expense accounts."""
    accounts = _accounts_by_code(
        db, org_id=org_id, types=(AccountType.REVENUE, AccountType.EXPENSE)
    )
    totals = _debit_credit_totals(db, accounts=accounts, from_date=from_date, to_date=to_date)

    revenue, expenses = [], []
    total_revenue = total_expenses = 0
    for code, account in sorted(accounts.items()):
        debit, credit = totals.get(code, (0, 0))
        if account.type == AccountType.REVENUE:
            balance = credit - debit
            revenue.append(
                StatementLine(account=code, account_name=account.name, balance_minor=balance)
            )
            total_revenue += balance
        else:
            balance = debit - credit
            expenses.append(
                StatementLine(account=code, account_name=account.name, balance_minor=balance)
            )
            total_expenses += balance

    return IncomeStatementOut(
        from_date=from_date,
        to_date=to_date,
        revenue=revenue,
        total_revenue_minor=total_revenue,
        expenses=expenses,
        total_expenses_minor=total_expenses,
        net_income_minor=total_revenue - total_expenses,
    )
