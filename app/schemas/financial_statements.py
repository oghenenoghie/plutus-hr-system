from datetime import date

from pydantic import BaseModel


class StatementLine(BaseModel):
    account: str
    account_name: str
    balance_minor: int


class BalanceSheetOut(BaseModel):
    as_of: date | None
    assets: list[StatementLine]
    total_assets_minor: int
    liabilities: list[StatementLine]
    total_liabilities_minor: int
    equity: list[StatementLine]
    total_equity_minor: int


class IncomeStatementOut(BaseModel):
    from_date: date | None
    to_date: date | None
    revenue: list[StatementLine]
    total_revenue_minor: int
    expenses: list[StatementLine]
    total_expenses_minor: int
    net_income_minor: int
