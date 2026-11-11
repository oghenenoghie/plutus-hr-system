from datetime import date

from pydantic import BaseModel, EmailStr


class StatementLine(BaseModel):
    account: str
    account_name: str
    balance_minor: int
    # None for a line the statement works out rather than an account in the
    # chart (the profit and loss reserve, postings to unknown accounts).
    account_number: str | None = None


class StatementSection(BaseModel):
    """One block of a statement: its accounts by number, and their total."""

    category: str
    label: str
    lines: list[StatementLine]
    total_minor: int


class BalanceSheetOut(BaseModel):
    """The balance sheet in the vertical form, top to bottom: fixed
    (non-current) assets, current assets, less current liabilities, net
    current assets, total assets less current liabilities, less non-current
    liabilities, net assets; then capital and reserves, which equal net
    assets. The profit and loss reserve is every profit and loss account's
    result up to the date, so the sheet balances without a year-end close.
    """

    as_of: date | None
    non_current_assets: StatementSection
    current_assets: StatementSection
    current_liabilities: StatementSection
    net_current_assets_minor: int
    total_assets_less_current_liabilities_minor: int
    non_current_liabilities: StatementSection
    net_assets_minor: int
    capital_and_reserves: StatementSection
    profit_and_loss_reserve_minor: int
    # Ledger accounts with postings that aren't in the chart of accounts.
    # Their net balance is shown as one line so the sheet still balances;
    # adding them to the chart puts them in the right section.
    unclassified_accounts: list[str]
    balanced: bool
    # The same figures by account type.
    assets: list[StatementLine]
    total_assets_minor: int
    liabilities: list[StatementLine]
    total_liabilities_minor: int
    equity: list[StatementLine]
    total_equity_minor: int


class IncomeStatementOut(BaseModel):
    """Sales less cost of sales is gross profit; plus other income, less
    overheads, is net profit."""

    from_date: date | None
    to_date: date | None
    sales: StatementSection
    cost_of_sales: StatementSection
    gross_profit_minor: int
    other_income: StatementSection
    overheads: StatementSection
    # The same figures by account type.
    revenue: list[StatementLine]
    total_revenue_minor: int
    expenses: list[StatementLine]
    total_expenses_minor: int
    net_income_minor: int


class EmailFinancialStatementRequest(BaseModel):
    # No natural counterparty for an internal financial statement, so a
    # recipient must always be given explicitly.
    to: EmailStr
