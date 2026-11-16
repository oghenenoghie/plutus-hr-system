import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import ColumnElement, Date, cast, func, select
from sqlalchemy.orm import Session

from app.domain.accounting.numbering import (
    CATEGORY_LABELS,
    CATEGORY_TYPE,
    DEFAULT_CATEGORY,
    AccountCategory,
)
from app.models.chart_account import AccountType, ChartAccount
from app.models.fixed_asset import FixedAsset, FixedAssetStatus
from app.models.journal_entry import JournalEntry, JournalSourceType
from app.models.ledger import LedgerEntry
from app.schemas.financial_statements import (
    BalanceSheetOut,
    IncomeStatementOut,
    StatementLine,
    StatementSection,
)
from app.services.posting import today_lagos

PROFIT_AND_LOSS_RESERVE = "profit_and_loss_reserve"
UNCLASSIFIED = "unclassified"

# The fixed assets block shows two figures, whatever accounts the chart has
# for them: everything at cost, less everything written off it. The asset by
# asset breakdown is the fixed asset register's depreciation schedule, not
# the balance sheet, which is a summary (the reviewing accountant's note).
FIXED_ASSETS_AT_COST = "fixed_assets_at_cost"
FIXED_ASSETS_WRITTEN_OFF = "fixed_assets_written_off"

LEASE_LIABILITY = "lease_liability"
LEASE_DUE_WITHIN_ONE_YEAR = "lease_liability_due_within_one_year"
LEASE_DUE_AFTER_ONE_YEAR = "lease_liability_due_after_one_year"

# The names the statements give each block, as the reviewing accountant
# reads them: fixed assets, not non-current assets; liabilities by when
# they fall due.
STATEMENT_LABELS: dict[AccountCategory, str] = {
    **CATEGORY_LABELS,
    AccountCategory.NON_CURRENT_ASSET: "Fixed assets",
    AccountCategory.CURRENT_LIABILITY: "Current liabilities: amounts falling due within one year",
    AccountCategory.NON_CURRENT_LIABILITY: (
        "Long-term liabilities: amounts falling due after more than one year"
    ),
}

_DEPRECIATED_EVENT_PREFIX = "asset.depreciated:"


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


def _accounting_date() -> ColumnElement[date]:
    """A ledger line's accounting date: its journal's entry date. Lines from
    before journals carried one fall back to the day they were posted."""
    return func.coalesce(JournalEntry.entry_date, cast(LedgerEntry.created_at, Date))


def _debit_credit_totals(
    db: Session, *, from_date: date | None, to_date: date | None
) -> dict[str, tuple[int, int]]:
    """Debits and credits per ledger account over the period, for every
    account posted to, whether or not it's in the chart. The period is the
    accounting date, so a charge dated 31 December lands in December however
    early it was entered."""
    accounting_date = _accounting_date()
    stmt = (
        select(
            LedgerEntry.account,
            func.coalesce(func.sum(LedgerEntry.debit_minor), 0),
            func.coalesce(func.sum(LedgerEntry.credit_minor), 0),
        )
        .outerjoin(JournalEntry, JournalEntry.id == LedgerEntry.journal_entry_id)
        .group_by(LedgerEntry.account)
    )
    if from_date is not None:
        stmt = stmt.where(accounting_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(accounting_date <= to_date)
    return {account: (int(debit), int(credit)) for account, debit, credit in db.execute(stmt)}


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
        label=STATEMENT_LABELS[category],
        lines=lines,
        total_minor=sum(line.balance_minor for line in lines),
    )


def _is_written_off(line: StatementLine) -> bool:
    """A contra account that carries what's been written off a fixed asset:
    accumulated depreciation or amortisation, however the chart names it."""
    text = f"{line.account} {line.account_name}".lower()
    return any(word in text for word in ("accumulated", "depreciation", "amortis", "amortiz"))


def _fixed_asset_summary(lines: list[StatementLine]) -> list[StatementLine]:
    """Every fixed asset account at cost, as one figure, and every account
    written off them, as another (a credit, so negative)."""
    cost = sum(line.balance_minor for line in lines if not _is_written_off(line))
    written_off = sum(line.balance_minor for line in lines if _is_written_off(line))
    summary = []
    if cost:
        summary.append(
            StatementLine(
                account=FIXED_ASSETS_AT_COST,
                account_name="Fixed assets at cost",
                balance_minor=cost,
            )
        )
    if written_off:
        summary.append(
            StatementLine(
                account=FIXED_ASSETS_WRITTEN_OFF,
                account_name="Accumulated depreciation and amortisation",
                balance_minor=written_off,
            )
        )
    return summary


def _months_between(start: date, end: date) -> int:
    """Whole months from start to end, counting a month only once its day
    has come round (15 Jan to 14 Feb is 0, to 15 Feb is 1)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _lease_due_after_one_year(db: Session, *, org_id: uuid.UUID, as_of: date) -> int:
    """The part of the lease liability that falls due after more than a year:
    for each lease still running, its equal monthly instalments (the
    liability is the lease's cost, spread over its term) for the months left
    after the next twelve. Everything else, including anything overdue, is
    due within one year."""
    leases = db.scalars(
        select(FixedAsset).where(
            FixedAsset.org_id == org_id,
            FixedAsset.acquisition_type == "leased",
            FixedAsset.status == FixedAssetStatus.ACTIVE,
            FixedAsset.acquisition_date <= as_of,
        )
    )
    after = 0
    for lease in leases:
        term = lease.lease_term_months or 0
        if term <= 0:
            continue
        months_left = term - _months_between(lease.acquisition_date, as_of)
        if months_left > 12:
            after += lease.cost_minor * (months_left - 12) // term
    return after


def _split_lease_liability(
    lines: dict[AccountCategory, list[StatementLine]], *, due_after: int
) -> None:
    """Moves the lease liability's current portion into current liabilities,
    leaving only what falls due after more than a year below."""
    long_term = lines[AccountCategory.NON_CURRENT_LIABILITY]
    lease = next((line for line in long_term if line.account == LEASE_LIABILITY), None)
    if lease is None:
        return
    after = min(max(due_after, 0), lease.balance_minor) if lease.balance_minor > 0 else 0
    within = lease.balance_minor - after
    long_term.remove(lease)
    if within:
        lines[AccountCategory.CURRENT_LIABILITY].append(
            StatementLine(
                account=LEASE_DUE_WITHIN_ONE_YEAR,
                account_name=f"{lease.account_name} — due within one year",
                balance_minor=within,
            )
        )
    if after:
        long_term.append(
            StatementLine(
                account=LEASE_DUE_AFTER_ONE_YEAR,
                account_name=f"{lease.account_name} — due after more than one year",
                balance_minor=after,
            )
        )


def balance_sheet(db: Session, *, org_id: uuid.UUID, as_of: date | None = None) -> BalanceSheetOut:
    """Everything posted up to `as_of` (all time if omitted). Accounts with
    nothing on them are left out, so the sheet shows only what's there."""
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
        elif balance:
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

    equity_lines = list(lines[AccountCategory.EQUITY])
    if profit:
        equity_lines.append(
            StatementLine(
                account=PROFIT_AND_LOSS_RESERVE,
                account_name="Profit and Loss Reserve",
                balance_minor=profit,
            )
        )

    # The same figures by account type, account by account, before the
    # statement summarises fixed assets and splits the lease liability.
    assets = [*lines[AccountCategory.NON_CURRENT_ASSET], *lines[AccountCategory.CURRENT_ASSET]]
    liabilities = [
        *lines[AccountCategory.CURRENT_LIABILITY],
        *lines[AccountCategory.NON_CURRENT_LIABILITY],
    ]

    _split_lease_liability(
        lines,
        due_after=_lease_due_after_one_year(db, org_id=org_id, as_of=as_of or today_lagos()),
    )

    non_current_assets = _section(
        AccountCategory.NON_CURRENT_ASSET,
        _fixed_asset_summary(lines[AccountCategory.NON_CURRENT_ASSET]),
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


def _assets_awaiting_depreciation(
    db: Session, *, org_id: uuid.UUID, from_date: date | None, to_date: date | None
) -> int:
    """Active assets, owned or leased, with something left to write off, that
    were held in the period but have no depreciation (or amortisation)
    posted in it. Depreciation reaches the profit and loss account only once
    it's run, so the statement says when it hasn't been."""
    held = select(FixedAsset.id).where(
        FixedAsset.org_id == org_id,
        FixedAsset.status == FixedAssetStatus.ACTIVE,
        FixedAsset.cost_minor - FixedAsset.salvage_value_minor
        > FixedAsset.accumulated_depreciation_minor,
    )
    charged = select(JournalEntry.source_id).where(
        JournalEntry.org_id == org_id,
        JournalEntry.source_type == JournalSourceType.FIXED_ASSET,
        JournalEntry.source_event.like(f"{_DEPRECIATED_EVENT_PREFIX}%"),
    )
    if to_date is not None:
        held = held.where(FixedAsset.acquisition_date <= to_date)
        charged = charged.where(JournalEntry.entry_date <= to_date)
    if from_date is not None:
        charged = charged.where(JournalEntry.entry_date >= from_date)
    return int(
        db.scalar(
            select(func.count()).select_from(held.where(FixedAsset.id.not_in(charged)).subquery())
        )
        or 0
    )


def income_statement(
    db: Session, *, org_id: uuid.UUID, from_date: date | None = None, to_date: date | None = None
) -> IncomeStatementOut:
    """The profit and loss account for a period (all time if both dates are
    omitted). Accounts with nothing on them in the period are left out."""
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
        balance = _balance(account, totals)
        if not balance:
            continue
        line = _line(account, balance)
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
        assets_awaiting_depreciation=_assets_awaiting_depreciation(
            db, org_id=org_id, from_date=from_date, to_date=to_date
        ),
    )
