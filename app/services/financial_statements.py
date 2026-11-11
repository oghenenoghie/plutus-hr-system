import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.accounting.numbering import (
    CATEGORY_LABELS,
    CATEGORY_TYPE,
    DEFAULT_CATEGORY,
    AccountCategory,
)
from app.models.chart_account import AccountType, ChartAccount
from app.models.ledger import LedgerEntry
from app.schemas.financial_statements import (
    BalanceSheetOut,
    IncomeStatementOut,
    StatementLine,
    StatementSection,
)

PROFIT_AND_LOSS_RESERVE = "profit_and_loss_reserve"
UNCLASSIFIED = "unclassified"


def _category(account: ChartAccount) -> AccountCategory:
    """The account's category, or its type's default when the stored one
    doesn't fit its type."""
    try:
        category = AccountCategory(account.category)
    except ValueError:
        return DEFAULT_CATEGORY[account.type]
    if CATEGORY_TYPE[category] != account.type:
        return DEFAULT_CATEGORY[account.type]
    return category


def _chart(db: Session, *, org_id: uuid.UUID) -> list[ChartAccount]:
    return list(
        db.scalars(
            select(ChartAccount)
            .where(ChartAccount.org_id == org_id)
            .order_by(ChartAccount.account_number, ChartAccount.code)
        )
    )


def _debit_credit_totals(
    db: Session, *, from_date: date | None, to_date: date | None
) -> dict[str, tuple[int, int]]:
    """Debits and credits per ledger account over the period, for every
    account posted to, whether or not it's in the chart."""
    stmt = select(LedgerEntry)
    if from_date is not None:
        stmt = stmt.where(LedgerEntry.created_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(LedgerEntry.created_at < to_date + timedelta(days=1))

    totals: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for entry in db.scalars(stmt):
        debit, credit = totals[entry.account]
        totals[entry.account] = (debit + entry.debit_minor, credit + entry.credit_minor)
    return totals


def _balance(account: ChartAccount, totals: dict[str, tuple[int, int]]) -> int:
    """Debit-normal for assets and expenses, credit-normal otherwise."""
    debit, credit = totals.get(account.code, (0, 0))
    if account.type in (AccountType.ASSET, AccountType.EXPENSE):
        return debit - credit
    return credit - debit


def _line(account: ChartAccount, balance: int) -> StatementLine:
    return StatementLine(
        account=account.code,
        account_name=account.name,
        balance_minor=balance,
        account_number=account.account_number,
    )


def _section(category: AccountCategory, lines: list[StatementLine]) -> StatementSection:
    return StatementSection(
        category=category.value,
        label=CATEGORY_LABELS[category],
        lines=lines,
        total_minor=sum(line.balance_minor for line in lines),
    )


def balance_sheet(db: Session, *, org_id: uuid.UUID, as_of: date | None = None) -> BalanceSheetOut:
    """Everything posted up to `as_of` (all time if omitted)."""
    chart = _chart(db, org_id=org_id)
    totals = _debit_credit_totals(db, from_date=None, to_date=as_of)

    lines: dict[AccountCategory, list[StatementLine]] = defaultdict(list)
    profit = 0
    for account in chart:
        balance = _balance(account, totals)
        if account.type == AccountType.REVENUE:
            profit += balance
        elif account.type == AccountType.EXPENSE:
            profit -= balance
        else:
            lines[_category(account)].append(_line(account, balance))

    in_chart = {account.code for account in chart}
    unclassified = sorted(code for code in totals if code not in in_chart)
    unclassified_net_debit = sum(totals[code][0] - totals[code][1] for code in unclassified)
    if unclassified_net_debit:
        names = ", ".join(unclassified)
        if unclassified_net_debit > 0:
            lines[AccountCategory.CURRENT_ASSET].append(
                StatementLine(
                    account=UNCLASSIFIED,
                    account_name=f"Accounts not in the chart ({names})",
                    balance_minor=unclassified_net_debit,
                )
            )
        else:
            lines[AccountCategory.CURRENT_LIABILITY].append(
                StatementLine(
                    account=UNCLASSIFIED,
                    account_name=f"Accounts not in the chart ({names})",
                    balance_minor=-unclassified_net_debit,
                )
            )

    reserve = StatementLine(
        account=PROFIT_AND_LOSS_RESERVE,
        account_name="Profit and Loss Reserve",
        balance_minor=profit,
    )
    equity_lines = [*lines[AccountCategory.EQUITY], reserve]

    non_current_assets = _section(
        AccountCategory.NON_CURRENT_ASSET, lines[AccountCategory.NON_CURRENT_ASSET]
    )
    current_assets = _section(AccountCategory.CURRENT_ASSET, lines[AccountCategory.CURRENT_ASSET])
    current_liabilities = _section(
        AccountCategory.CURRENT_LIABILITY, lines[AccountCategory.CURRENT_LIABILITY]
    )
    non_current_liabilities = _section(
        AccountCategory.NON_CURRENT_LIABILITY, lines[AccountCategory.NON_CURRENT_LIABILITY]
    )
    capital_and_reserves = _section(AccountCategory.EQUITY, equity_lines)

    net_current_assets = current_assets.total_minor - current_liabilities.total_minor
    total_assets_less_current_liabilities = non_current_assets.total_minor + net_current_assets
    net_assets = total_assets_less_current_liabilities - non_current_liabilities.total_minor

    assets = [*non_current_assets.lines, *current_assets.lines]
    liabilities = [*current_liabilities.lines, *non_current_liabilities.lines]
    return BalanceSheetOut(
        as_of=as_of,
        non_current_assets=non_current_assets,
        current_assets=current_assets,
        current_liabilities=current_liabilities,
        net_current_assets_minor=net_current_assets,
        total_assets_less_current_liabilities_minor=total_assets_less_current_liabilities,
        non_current_liabilities=non_current_liabilities,
        net_assets_minor=net_assets,
        capital_and_reserves=capital_and_reserves,
        profit_and_loss_reserve_minor=profit,
        unclassified_accounts=unclassified,
        balanced=net_assets == capital_and_reserves.total_minor,
        assets=assets,
        total_assets_minor=sum(line.balance_minor for line in assets),
        liabilities=liabilities,
        total_liabilities_minor=sum(line.balance_minor for line in liabilities),
        equity=equity_lines,
        total_equity_minor=capital_and_reserves.total_minor,
    )


def income_statement(
    db: Session, *, org_id: uuid.UUID, from_date: date | None = None, to_date: date | None = None
) -> IncomeStatementOut:
    """The profit and loss account for a period (all time if both dates are
    omitted)."""
    chart = [
        account
        for account in _chart(db, org_id=org_id)
        if account.type in (AccountType.REVENUE, AccountType.EXPENSE)
    ]
    totals = _debit_credit_totals(db, from_date=from_date, to_date=to_date)

    lines: dict[AccountCategory, list[StatementLine]] = defaultdict(list)
    revenue: list[StatementLine] = []
    expenses: list[StatementLine] = []
    for account in chart:
        line = _line(account, _balance(account, totals))
        lines[_category(account)].append(line)
        (revenue if account.type == AccountType.REVENUE else expenses).append(line)

    sales = _section(AccountCategory.REVENUE, lines[AccountCategory.REVENUE])
    cost_of_sales = _section(AccountCategory.COST_OF_SALES, lines[AccountCategory.COST_OF_SALES])
    other_income = _section(AccountCategory.OTHER_INCOME, lines[AccountCategory.OTHER_INCOME])
    overheads = _section(
        AccountCategory.OPERATING_EXPENSE, lines[AccountCategory.OPERATING_EXPENSE]
    )
    total_revenue = sum(line.balance_minor for line in revenue)
    total_expenses = sum(line.balance_minor for line in expenses)
    return IncomeStatementOut(
        from_date=from_date,
        to_date=to_date,
        sales=sales,
        cost_of_sales=cost_of_sales,
        gross_profit_minor=sales.total_minor - cost_of_sales.total_minor,
        other_income=other_income,
        overheads=overheads,
        revenue=revenue,
        total_revenue_minor=total_revenue,
        expenses=expenses,
        total_expenses_minor=total_expenses,
        net_income_minor=total_revenue - total_expenses,
    )
